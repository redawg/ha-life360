#!/usr/bin/env python3
"""Create Life360 zone enter/leave burst automations on HA Green."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

HA_URL = os.environ.get("HA_URL", "http://172.16.255.250:8123").rstrip("/")
TOKEN = os.environ.get(
    "HA_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJlNDM2OWE2YTVmYjk0ODIzOTFmNDA3OTdiM2NiZmFiYyIsImlhdCI6MTc3ODU0NzMyNCwiZXhwIjoyMDkzOTA3MzI0fQ.Kh_2jOBqDJnevRqvrEGnZ1E849jrRK0_-SOdr6lr2Fs",
)

LIFE360_TRACKERS = [
    "device_tracker.life360_andrew_schoenfeld",
    "device_tracker.life360_carol_schoenfeld",
    "device_tracker.life360_sidney_schoenfeld",
    "device_tracker.life360_hunter",
    "device_tracker.life360_mom",
]


def api(method: str, path: str, data: dict | None = None) -> tuple[int, object]:
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(HA_URL + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, parsed


def get_automations() -> list[dict]:
    _, data = api("GET", "/api/config/automation/config")
    return data if isinstance(data, list) else []


def upsert_automation(config: dict) -> tuple[int, object]:
    auto_id = config["id"]
    return api("POST", f"/api/config/automation/config/{auto_id}", config)


def build_zone_automation(auto_id: str, alias: str, event: str) -> dict:
    triggers = [
        {
            "platform": "zone",
            "entity_id": tracker,
            "zone": "zone.home",
            "event": event,
        }
        for tracker in LIFE360_TRACKERS
    ]
    return {
        "id": auto_id,
        "alias": alias,
        "description": (
            "Request Life360 burst location updates when a family member "
            f"{event}s home so the map marker refreshes promptly."
        ),
        "mode": "parallel",
        "max": 3,
        "trigger": triggers,
        "action": [
            {
                "action": "life360.update_location",
                "target": {"entity_id": "{{ trigger.entity_id }}"},
            }
        ],
    }


def main() -> int:
    existing = {a.get("id") for a in get_automations()}
    print(f"Existing automations: {len(existing)}")

    configs = [
        build_zone_automation(
            "life360_burst_on_home_enter",
            "Life360 burst on home enter",
            "enter",
        ),
        build_zone_automation(
            "life360_burst_on_home_leave",
            "Life360 burst on home leave",
            "leave",
        ),
    ]

    for config in configs:
        status, resp = upsert_automation(config)
        print(f"{config['id']}: HTTP {status}")
        if status >= 400:
            print(f"  error: {resp}")
            return 1

    status, resp = api("POST", "/api/services/automation/reload", {})
    print(f"automation/reload: HTTP {status}")
    if status >= 400:
        print(f"  error: {resp}")
        return 1

    print("AUTOMATIONS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
