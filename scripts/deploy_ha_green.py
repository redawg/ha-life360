#!/usr/bin/env python3
"""Deploy custom_components/life360 to HA Green via SSH/SCP."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    import paramiko
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko", "-q"])
    import paramiko

HOST = "172.16.255.250"
HA_URL = f"http://{HOST}:8123"
LOCAL_ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "life360"
REMOTE_ROOT = "/config/custom_components/life360"
ENTRY_ID = "01KFWBEQ7MQJXMEMARTBSGA138"

CANDIDATES = [
    ("root", os.environ.get("HA_SSH_PASSWORD", "")),
    ("homeassistant", os.environ.get("HA_SSH_PASSWORD", "")),
]


def upload_dir(sftp: paramiko.SFTPClient, local: Path, remote: str) -> None:
    try:
        sftp.mkdir(remote)
    except OSError:
        pass
    for item in local.iterdir():
        rpath = f"{remote}/{item.name}"
        if item.is_dir():
            upload_dir(sftp, item, rpath)
        else:
            print(f"PUT {item.name} -> {rpath}")
            sftp.put(str(item), rpath)


def try_connect(user: str, password: str) -> paramiko.SSHClient | None:
    if not password:
        return None
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            HOST,
            username=user,
            password=password,
            timeout=15,
            look_for_keys=False,
            allow_agent=False,
        )
        print(f"CONNECTED as {user}")
        return client
    except Exception as exc:
        print(f"FAIL {user}: {exc}")
        client.close()
        return None


def reload_life360() -> None:
    token = os.environ.get("HA_TOKEN", "")
    if not token:
        print("HA_TOKEN not set; skipping integration reload")
        return
    body = json.dumps({"entry_id": ENTRY_ID}).encode()
    req = urllib.request.Request(
        f"{HA_URL}/api/services/homeassistant/reload_config_entry",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Reload life360 integration: HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        print(f"Reload failed: HTTP {exc.code} {exc.read().decode()[:300]}")


def main() -> int:
    password = os.environ.get("HA_SSH_PASSWORD", "")
    client = None
    for user, _ in CANDIDATES:
        client = try_connect(user, password)
        if client:
            break
    if not client:
        print("SSH_AUTH_FAILED — set HA_SSH_PASSWORD and retry")
        return 1

    stdin, stdout, stderr = client.exec_command(f"mkdir -p {REMOTE_ROOT}")
    stdout.channel.recv_exit_status()
    sftp = client.open_sftp()
    upload_dir(sftp, LOCAL_ROOT, REMOTE_ROOT)
    sftp.close()

    stdin, stdout, stderr = client.exec_command(
        f"cat {REMOTE_ROOT}/manifest.json"
    )
    print("Remote manifest.json:")
    print(stdout.read().decode())

    client.close()
    reload_life360()
    print("DEPLOY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
