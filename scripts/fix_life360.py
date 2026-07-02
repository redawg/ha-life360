#!/usr/bin/env python3
"""Deploy Life360 patch, update account password, and reload integration."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HA_URL = os.environ.get("HA_URL", "http://172.16.255.250:8123").rstrip("/")
HA_WS = HA_URL.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"


def _default_ha_token() -> str:
    setup = Path(__file__).resolve().parent / "setup_automations.py"
    if setup.exists():
        match = re.search(r'"(eyJ[^"]+)"', setup.read_text(encoding="utf-8"))
        if match:
            return match.group(1)
    return ""


HA_TOKEN = os.environ.get("HA_TOKEN") or _default_ha_token()
ENTRY_ID = os.environ.get("LIFE360_ENTRY_ID", "01KFWBEQ7MQJXMEMARTBSGA138")
REPO = os.environ.get("HACS_REPO", "redawg/ha-life360")
EMAIL = os.environ.get("LIFE360_EMAIL", "")
PASSWORD = os.environ.get("LIFE360_PASSWORD", "")


async def ws_call(ws, msg_id: int, payload: dict) -> dict:
    await ws.send_json({"id": msg_id, **payload})
    while True:
        msg = await ws.receive_json()
        if msg.get("id") == msg_id:
            return msg


async def hacs_deploy(ws) -> bool:
    msg_id = 1
    msg = await ws_call(
        ws,
        msg_id,
        {"type": "hacs/repositories/add", "repository": REPO, "category": "integration"},
    )
    print(f"HACS add repo: success={msg.get('success')} error={msg.get('error')}")

    msg_id += 1
    msg = await ws_call(ws, msg_id, {"type": "hacs/repositories/list"})
    repos = msg.get("result") or []
    target = next((r for r in repos if r.get("full_name") == REPO), None)
    if not target:
        print("HACS repo not found")
        return False

    msg_id += 1
    msg = await ws_call(
        ws,
        msg_id,
        {"type": "hacs/repository/download", "repository": str(target["id"])},
    )
    print(f"HACS download: success={msg.get('success')} error={msg.get('error')}")
    return bool(msg.get("success"))


def post_flow(path: str, data: dict) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    req = urllib.request.Request(
        HA_URL + path, data=json.dumps(data).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"message": body}


def update_account_via_options_flow() -> bool:
    """Re-enter Life360 password through the HA options flow."""
    code, resp = post_flow(
        "/api/config/config_entries/options/flow",
        {"handler": "life360", "entry_id": ENTRY_ID},
    )
    if code >= 400:
        print(f"Options flow start failed: HTTP {code} {resp}")
        return False

    flow_id = resp["flow_id"]
    step = resp["step_id"]
    print(f"Options flow started: step={step}")

    # init step: keep current options
    if step == "init":
        schema = resp.get("data_schema") or []
        defaults: dict = {}
        for field in schema:
            if field.get("default") is not None:
                defaults[field["name"]] = field["default"]
        code, resp = post_flow(
            f"/api/config/config_entries/options/flow/{flow_id}",
            defaults or {"driving": False},
        )
        if code >= 400:
            print(f"Options init failed: HTTP {code} {resp}")
            return False
        step = resp["step_id"]
        print(f"Options flow step: {step}")

    if step == "acct_menu":
        code, resp = post_flow(
            f"/api/config/config_entries/options/flow/{flow_id}",
            {"next_step_id": "mod_acct_sel"},
        )
        if code >= 400:
            print(f"Options acct_menu failed: HTTP {code} {resp}")
            return False
        step = resp["step_id"]
        print(f"Options flow step: {step}")

    if step == "mod_acct_sel":
        code, resp = post_flow(
            f"/api/config/config_entries/options/flow/{flow_id}",
            {"accounts": EMAIL},
        )
        if code >= 400:
            print(f"Options mod_acct_sel failed: HTTP {code} {resp}")
            return False
        step = resp["step_id"]
        print(f"Options flow step: {step}")

    if step == "acct_authorization":
        code, resp = post_flow(
            f"/api/config/config_entries/options/flow/{flow_id}",
            {"next_step_id": "acct_username_password"},
        )
        if code >= 400:
            print(f"Switch to password auth failed: HTTP {code} {resp}")
            return False
        step = resp["step_id"]
        print(f"Options flow step: {step}")

    if step == "acct_username_password":
        code, resp = post_flow(
            f"/api/config/config_entries/options/flow/{flow_id}",
            {"username": EMAIL, "password": PASSWORD, "enabled": True},
        )
        if code >= 400:
            print(f"Password update failed: HTTP {code} {resp}")
            return False
        if resp.get("type") == "form" and resp.get("errors"):
            print(f"Password update errors: {resp['errors']}")
            return False
        step = resp.get("step_id")
        print(f"Options flow step after password: {step}")

    if step == "acct_menu":
        code, resp = post_flow(
            f"/api/config/config_entries/options/flow/{flow_id}",
            {"next_step_id": "done"},
        )
        if code >= 400:
            print(f"Options done failed: HTTP {code} {resp}")
            return False

    if resp.get("type") == "create_entry":
        print("OPTIONS_FLOW_OK")
        return True

    print(f"Options flow ended unexpectedly: {json.dumps(resp)[:500]}")
    return False


async def reload_integration(ws) -> None:
    msg = await ws_call(
        ws,
        10,
        {
            "type": "call_service",
            "domain": "homeassistant",
            "service": "reload_config_entry",
            "service_data": {"entry_id": ENTRY_ID},
        },
    )
    print(f"Reload integration: success={msg.get('success')} error={msg.get('error')}")


async def main() -> int:
    if not HA_TOKEN:
        print("HA_TOKEN required")
        return 1

    creds_ok = bool(EMAIL and PASSWORD)
    if creds_ok and not update_account_via_options_flow():
        print("Options flow failed; continuing with deploy/reload")
    elif not creds_ok:
        print("LIFE360_EMAIL/PASSWORD not set; skipping options flow")

    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(HA_WS, timeout=30) as ws:
            hello = await ws.receive_json()
            if hello.get("type") != "auth_required":
                print("Unexpected WS hello:", hello)
                return 1
            await ws.send_json({"type": "auth", "access_token": HA_TOKEN})
            auth = await ws.receive_json()
            if auth.get("type") != "auth_ok":
                print("WS auth failed:", auth)
                return 1

            if not await hacs_deploy(ws):
                print("HACS deploy failed; continuing to reload")

            await reload_integration(ws)

    print("FIX_LIFE360_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
