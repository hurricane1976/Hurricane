#!/usr/bin/env python3
"""Appends one observation of the off-box fleet to website/data/fleet-pulse.jsonl.

Beacon keeps no wake logs for the agents that run on tidalwake.org (Tidal and
River), so the only honest way to chart their activity is to record what Beacon
can actually observe, every waking, and let the series accrue.

This fetches Tidal's published manifest and notes its `updated` timestamp. A
new `updated` value Beacon hasn't recorded before is proof Tidal woke since the
last check. Run from deploy.sh (before build_metrics.py) or standalone. It
never fails the deploy -- a network error just records tidal_reachable=false.
"""
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
PULSE = DATA / "fleet-pulse.jsonl"
MANIFEST = "https://tidalwake.org/.well-known/agent.json"

# If nothing changed and we recorded within this window, don't add a line.
HEARTBEAT_SEC = 6 * 3600


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _last_record():
    if not PULSE.exists():
        return None
    lines = [l for l in PULSE.read_text().splitlines() if l.strip()]
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def fetch_tidal() -> dict:
    try:
        req = urllib.request.Request(
            MANIFEST, headers={"User-Agent": "beacon-fleet-pulse/1"}
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            m = json.load(r)
        return {
            "tidal_reachable": True,
            "tidal_updated": m.get("updated"),
            "tidal_cadence": m.get("wake_cadence"),
        }
    except Exception as e:  # noqa: BLE001 -- deploy must never break here
        return {
            "tidal_reachable": False,
            "tidal_updated": None,
            "tidal_cadence": None,
            "error": str(e)[:120],
        }


def main() -> None:
    DATA.mkdir(exist_ok=True)
    obs = fetch_tidal()
    obs["observed_at"] = _now()

    last = _last_record()
    if last is not None:
        same_updated = bool(obs.get("tidal_updated")) and (
            obs["tidal_updated"] == last.get("tidal_updated")
        )
        try:
            last_dt = datetime.strptime(
                last["observed_at"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
            recent = (
                datetime.now(timezone.utc) - last_dt
            ).total_seconds() < HEARTBEAT_SEC
        except Exception:  # noqa: BLE001
            recent = False
        if (
            same_updated
            and obs["tidal_reachable"] == last.get("tidal_reachable")
            and recent
        ):
            print("fleet-pulse: no change since last record, skipping")
            return

    with PULSE.open("a") as f:
        f.write(json.dumps(obs, separators=(",", ":")) + "\n")
    print(
        f"fleet-pulse: recorded {obs['observed_at']} "
        f"tidal_updated={obs.get('tidal_updated')} "
        f"reachable={obs['tidal_reachable']}"
    )


if __name__ == "__main__":
    main()
