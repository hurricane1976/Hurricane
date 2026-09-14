#!/usr/bin/env python3
"""Crash-safety counterpart to fleet_telemetry.py, for Beacon's own
website/data/observability.jsonl (the store website/build_observability.py
reads to render /observability.html).

Called by wake.sh right after fleet_telemetry.py:

    python3 record_observability_row.py <envelope.json> <TS> <claude_exit>

The gap this closes: build_observability.py is only ever invoked from
website/deploy.sh, which wake.sh gates on a zero exit code (a crashed session
may have left NOTES.md etc. mid-edit, so a full site rebuild+redeploy on
crash was never safe). That means a crashed/timed-out waking's logs/<ts>.json
is typically empty or unparseable too (claude never got to emit the
`--output-format json` envelope), so build_observability.py's own
scan_json_logs() silently skips it even when it does run later. Net effect:
Beacon's own per-run dashboard quietly under-reports its errors, while the
sibling fleet-telemetry.jsonl pipeline already guards against exactly this
(see fleet_telemetry.py's docstring) by writing an is_error row unconditionally.
Flagged from outside the fleet -- Moltbook, @wraslousth, 2026-09-14, on the
"per-step tracing" thread -- ported the same fix here.

Only writes something when there's no usable envelope (a real completed run,
success or not, is already covered by the normal scan_json_logs() path once
build_observability.py next runs). Writes straight into STORE using
build_observability's own load_store()/save_store() so the row round-trips
through the exact same merge a later successful waking performs -- and won't
be clobbered by it, since scan_json_logs() only ever produces a row for a
timestamp whose envelope parses cleanly, which a crashed run's never will.
The row won't be visible on /observability.html until the next successful
deploy re-renders the page from STORE, but it isn't lost. Never fatal: any
problem here prints a note and exits 0, matching fleet_telemetry.py's
contract.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "website"))

AGENT = "Beacon"


def _iso_from_ts(ts: str) -> str:
    """20260907T040233Z -> 2026-09-07T04:02:33Z (same as build_observability)."""
    return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[9:11]}:{ts[11:13]}:{ts[13:15]}Z"


def main():
    envelope_path = sys.argv[1] if len(sys.argv) > 1 else ""
    stamp = sys.argv[2] if len(sys.argv) > 2 else ""
    try:
        exit_code = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    except ValueError:
        exit_code = 0

    if exit_code == 0:
        return  # normal path (deploy.sh -> build_observability.py) covers this

    env = None
    if envelope_path and os.path.isfile(envelope_path) and os.path.getsize(envelope_path) > 0:
        try:
            loaded = json.load(open(envelope_path))
            if isinstance(loaded, dict) and loaded.get("type") == "result":
                env = loaded
        except (OSError, ValueError):
            env = None

    if env is not None:
        return  # a clean envelope exists; scan_json_logs() will pick it up normally

    try:
        import build_observability as bo
    except Exception as e:
        print(f"(record_observability_row: import failed, skipping: {e})")
        return

    row = {
        "agent": AGENT,
        "ts": _iso_from_ts(stamp),
        "cost_usd": None,
        "turns": None,
        "duration_ms": None,
        "duration_api_ms": None,
        "input_tokens": None,
        "output_tokens": None,
        "cache_read_tokens": None,
        "cache_creation_tokens": None,
        "is_error": True,
        "subtype": "error_during_execution",
        "terminal_reason": "timeout" if exit_code in (124, 137) else "execution_error",
        "model": None,
    }
    try:
        store = bo.load_store()
        key = f"{row['agent']}:{row['ts']}"
        if key not in store:  # don't clobber a row a later rerun already wrote
            store[key] = row
            bo.save_store(store)
            print(f"(record_observability_row: wrote crash row ts={row['ts']} exit={exit_code})")
    except Exception as e:
        print(f"(record_observability_row: write failed: {e})")


if __name__ == "__main__":
    main()
