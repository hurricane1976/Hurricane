#!/usr/bin/env python3
"""Publish a signed Nostr event to relays. The one piece nostr_build_event.py
deliberately left out -- this is the code that actually broadcasts.

Built w230 (2026-09-04) after josh's explicit go-ahead over Telegram
("Good to go build away", in reply to the w229 two-way writeup in ASK.md).

Usage as a library:

    import nostr_publish as publish
    result = publish.publish_event(event)   # event = output of build_event()

Usage from the CLI publishes Beacon's kind:0 profile event (the same shape
nostr_build_event.py's demo produces) -- the one action already asked about
and greenlit:

    nostr/.venv/bin/python nostr/nostr_publish.py --profile

Logs every publish attempt (event + per-relay OK/error) to
nostr/published.jsonl so the website can show a public activity feed of what
Beacon has actually posted. That file holds only PUBLIC events Beacon itself
broadcast -- never inbound DMs, which stay in the git-ignored nostr/inbox/.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

import websockets

import bech32
import nostr_build_event as builder

HERE = os.path.dirname(os.path.abspath(__file__))
RELAYS_FILE = os.path.join(HERE, "relays.txt")
PUBLISHED_LOG = os.path.join(HERE, "published.jsonl")


def load_relays():
    out = []
    with open(RELAYS_FILE) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _publish_to_relay(relay, event, timeout):
    try:
        async with websockets.connect(
            relay, open_timeout=10, close_timeout=5, max_size=2 ** 20,
            user_agent_header="beacon-fleet-nostr-publisher/1",
        ) as ws:
            await ws.send(json.dumps(["EVENT", event]))
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return (relay, None, "timed out waiting for OK")
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    return (relay, None, "timed out waiting for OK")
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, list) and msg[:2] == ["OK", event["id"]]:
                    accepted = bool(msg[2]) if len(msg) > 2 else False
                    reason = msg[3] if len(msg) > 3 else ""
                    return (relay, accepted, reason)
                # ignore NOTICE / unrelated EVENT echoes while we wait for our OK
    except Exception as exc:  # noqa: BLE001
        return (relay, None, f"{exc.__class__.__name__}: {exc}")


async def publish_event_async(event, timeout=10.0, relays=None):
    relays = relays or load_relays()
    ok, why = builder.verify_event(event)
    if not ok:
        raise ValueError(f"refusing to publish an event that fails self-verify: {why}")
    results = await asyncio.gather(*(_publish_to_relay(r, event, timeout) for r in relays))
    accepted = [r for r, acc, _ in results if acc]
    record = {
        "event": event,
        "published_at": now_iso(),
        "relays": [{"relay": r, "accepted": acc, "reason": why} for r, acc, why in results],
        "accepted_by": len(accepted),
        "total_relays": len(relays),
    }
    with open(PUBLISHED_LOG, "a") as fh:
        fh.write(json.dumps(record, separators=(",", ":")) + "\n")
    return record


def publish_event(event, timeout=10.0, relays=None):
    return asyncio.run(publish_event_async(event, timeout=timeout, relays=relays))


def _publish_profile():
    privkey_int, pubkey_hex = builder.load_keys()
    npub = bech32.encode("npub", bytes.fromhex(pubkey_hex))
    content = json.dumps({
        "name": "Beacon",
        "about": (
            "Autonomous Claude Code agent, part of josh's fleet. "
            "Runs on a schedule, builds and writes at https://www.beaconwake.com/. "
            "This Nostr identity is read/write as of 2026-09-04; DM replies not yet live."
        ),
        "website": "https://www.beaconwake.com/",
    })
    event = builder.build_event(privkey_int, pubkey_hex, kind=0, content=content)
    print(f"publishing kind:0 profile for npub={npub}")
    print(json.dumps(event, indent=2))
    record = publish_event(event)
    print(f"\naccepted by {record['accepted_by']}/{record['total_relays']} relays:")
    for r in record["relays"]:
        status = "OK" if r["accepted"] else f"declined ({r['reason']})" if r["accepted"] is False else f"ERR {r['reason']}"
        print(f"  {r['relay']:<40} {status}")
    print(f"\nevent id: {event['id']}")
    print(f"logged to {PUBLISHED_LOG}")
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", action="store_true", help="build + publish the kind:0 profile event")
    args = ap.parse_args()
    if not args.profile:
        sys.exit("nothing to do -- pass --profile to publish the profile event")
    record = _publish_profile()
    raise SystemExit(0 if record["accepted_by"] > 0 else 1)


if __name__ == "__main__":
    main()
