# Life360 map update patch (v0.10.1-aschoenfeld.3)

Fork of [pnbruckner/ha-life360](https://github.com/pnbruckner/ha-life360) with improvements for stuck map markers on home/away transitions.

## Changes

- **`device_tracker.py`**: Accept coordinate updates when location or Life360 place actually changed, even if GPS accuracy filter or `last_seen` ordering would normally reject them. Force map redraw when accepted coordinates move. Auto-request Life360 burst updates on zone transitions (60s debounce).
- **`coordinator.py`**: `always_update=True` on member coordinators so location writes propagate reliably.
- **`coordinator.py`**: Automatic re-authentication — retries with stored password or bearer token on login failure, on startup, and every 30 minutes for disabled/offline accounts. Accounts with a stored password are not auto-disabled (keeps retrying).
- **`coordinator.py`**: After successful re-auth, clear the failed-request lock and refresh data so trackers recover instead of staying stuck offline.

## Auto re-auth limits

- **Password stored**: Fully automatic — plugin logs in again when the token expires.
- **Bearer token only**: Retries the stored token automatically; if Life360 revoked it, you must paste a new token once in Configure (cannot be obtained without browser login).

## Deploy to HA Green

```powershell
$env:HA_TOKEN = "<long-lived-token>"
python scripts/deploy_hacs_ws.py
```

HACS custom repo: `redawg/ha-life360`

## HA automations

`scripts/setup_automations.py` creates:

- `automation.life360_burst_on_home_enter`
- `automation.life360_burst_on_home_leave`

Both call `life360.update_location` for all family Life360 trackers on `zone.home` enter/leave.

## Re-auth required

If `binary_sensor.life360_online_*` is `off`, re-enable the Life360 account in **Settings → Devices & services → Life360 → Configure**. Phone-verified accounts need an access token per upstream docs.
