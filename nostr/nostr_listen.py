#!/usr/bin/env python3
"""Nostr listener for the fleet's identity.

Connects to a short relay list, asks for everything addressed to our pubkey
(NIP-04 DMs kind:4, NIP-17 gift wraps kind:1059, mentions kind:1) plus any
events we might have authored (kind:0/1/3 -- there should be none), collects
until EOSE or a per-relay timeout, then disconnects.

NIP-04 DMs are decrypted locally (ECDH over secp256k1 + AES-256-CBC, both from
`cryptography`). Gift wraps (kind:1059 -- what modern clients use for private
DMs per NIP-17) are unwrapped via `nostr_nip59.py` (NIP-44 + NIP-59, added
w231 once josh asked to see live replies): rumor -> seal -> gift wrap, in
reverse.

This script itself never publishes -- listening and replying are kept as
separate steps; see `nostr_reply.py` for the bounded auto-acknowledgment that
runs after this.

Output:
  - append raw events (+ `_meta`) to nostr/inbox/<UTC-date>.jsonl  (git-ignored)
  - print a human summary to stdout (this is what lands in the waking log)

Usage:
  nostr/.venv/bin/python nostr/nostr_listen.py [--days N] [--timeout S]
"""
import argparse
import asyncio
import base64
import json
import os
import sys
import time
from datetime import datetime, timezone

import websockets
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import bech32
import nostr_nip59 as nip59

HERE = os.path.dirname(os.path.abspath(__file__))
KEYFILE = os.path.join(HERE, "..", "keys", "nostr.env")
RELAYS_FILE = os.path.join(HERE, "relays.txt")
INBOX_DIR = os.path.join(HERE, "inbox")


def load_keys():
    if not os.path.exists(KEYFILE):
        sys.exit(f"missing {KEYFILE} -- run nostr_keygen.py and save its output to keys/nostr.env first")
    env = {}
    with open(KEYFILE) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    priv_hex = env.get("NOSTR_PRIVKEY_HEX")
    pub_hex = env.get("NOSTR_PUBKEY_HEX")
    if not priv_hex or not pub_hex:
        # allow deriving from nsec if only that is present
        nsec = env.get("NOSTR_NSEC")
        if nsec:
            priv_bytes = bech32.decode("nsec", nsec)
            priv = ec.derive_private_key(int.from_bytes(priv_bytes, "big"), ec.SECP256K1())
            comp = priv.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
            return priv, comp[1:].hex()
        sys.exit("nostr.env has neither NOSTR_PRIVKEY_HEX nor NOSTR_NSEC")
    priv = ec.derive_private_key(int.from_bytes(bytes.fromhex(priv_hex), "big"), ec.SECP256K1())
    return priv, pub_hex


def load_relays():
    out = []
    with open(RELAYS_FILE) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


def nip04_decrypt(my_priv, sender_pub_hex, content):
    """content = '<b64 ciphertext>?iv=<b64 iv>' -> plaintext str, or None."""
    try:
        if "?iv=" not in content:
            return None
        ct_b64, iv_b64 = content.split("?iv=", 1)
        ct = base64.b64decode(ct_b64)
        iv = base64.b64decode(iv_b64)
        # x-only sender pubkey -> compressed point (even Y, BIP-340 convention)
        sender_pub = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256K1(), b"\x02" + bytes.fromhex(sender_pub_hex)
        )
        shared_x = my_priv.exchange(ec.ECDH(), sender_pub)  # 32-byte X coord
        cipher = Cipher(algorithms.AES(shared_x), modes.CBC(iv))
        dec = cipher.decryptor()
        padded = dec.update(ct) + dec.finalize()
        pad = padded[-1]
        if 1 <= pad <= 16:
            padded = padded[:-pad]
        return padded.decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - best effort, we log the failure
        return f"[decrypt failed: {exc.__class__.__name__}: {exc}]"


async def drain_relay(relay, sub_id, filters, timeout, collected):
    """Connect, REQ, gather EVENTs until EOSE/timeout, CLOSE, disconnect."""
    got = 0
    try:
        async with websockets.connect(relay, open_timeout=10, close_timeout=5,
                                      max_size=2 ** 20, user_agent_header="beacon-fleet-nostr-listener/2") as ws:
            await ws.send(json.dumps(["REQ", sub_id, *filters]))
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, list) or not msg:
                    continue
                if msg[0] == "EVENT" and len(msg) >= 3:
                    ev = msg[2]
                    eid = ev.get("id")
                    if eid and eid not in collected:
                        ev["_meta"] = {"relay": relay, "seen_at": now_iso()}
                        collected[eid] = ev
                    got += 1
                elif msg[0] == "EOSE":
                    break
                elif msg[0] == "NOTICE":
                    print(f"  notice [{relay}]: {msg[1:]}", file=sys.stderr)
            try:
                await ws.send(json.dumps(["CLOSE", sub_id]))
            except Exception:
                pass
        return (relay, got, None)
    except Exception as exc:  # noqa: BLE001
        return (relay, got, f"{exc.__class__.__name__}: {exc}")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def main_async(args):
    priv, pub_hex = load_keys()
    priv_hex = format(priv.private_numbers().private_value, "064x")
    npub = bech32.encode("npub", bytes.fromhex(pub_hex))
    relays = load_relays()
    since = int(time.time()) - args.days * 86400

    filters = [
        {"kinds": [4], "#p": [pub_hex], "since": since, "limit": 200},
        {"kinds": [1059], "#p": [pub_hex], "since": since, "limit": 200},
        {"kinds": [1], "#p": [pub_hex], "since": since, "limit": 200},
        {"kinds": [0, 1, 3], "authors": [pub_hex], "limit": 50},
    ]
    sub_id = "beacon-ro-" + str(int(time.time()))

    print(f"nostr listener  npub={npub}")
    print(f"  pubkey={pub_hex}")
    print(f"  {len(relays)} relays, looking back {args.days}d, {args.timeout}s/relay")

    collected = {}
    results = await asyncio.gather(
        *(drain_relay(r, sub_id, filters, args.timeout, collected) for r in relays)
    )

    for relay, got, err in results:
        status = "ok" if err is None else f"ERR {err}"
        print(f"  {relay:<40} events:{got:<4} {status}")

    events = sorted(collected.values(), key=lambda e: e.get("created_at", 0))
    by_kind = {}
    for ev in events:
        by_kind[ev.get("kind")] = by_kind.get(ev.get("kind"), 0) + 1

    print(f"\n{len(events)} distinct event(s); by kind: {by_kind or '{}'}")

    dm_previews = []
    for ev in events:
        if ev.get("kind") == 4:
            pt = nip04_decrypt(priv, ev.get("pubkey", ""), ev.get("content", ""))
            ev["_meta"]["decrypted"] = pt
            when = datetime.fromtimestamp(ev.get("created_at", 0), timezone.utc).strftime("%Y-%m-%d %H:%M")
            preview = (pt or "")[:200].replace("\n", " ")
            dm_previews.append(f"  DM {when}  from {ev.get('pubkey','')[:12]}…  {preview!r}")
        elif ev.get("kind") == 1059:
            try:
                seal, rumor = nip59.unwrap_gift_wrap(priv_hex, ev)
                ev["_meta"]["unwrapped"] = {
                    "sender_pubkey": seal["pubkey"],
                    "rumor_id": rumor.get("id"),
                    "rumor_kind": rumor.get("kind"),
                    "content": rumor.get("content"),
                    "rumor_created_at": rumor.get("created_at"),
                }
                if rumor.get("kind") == 14:
                    when = datetime.fromtimestamp(ev.get("created_at", 0), timezone.utc).strftime("%Y-%m-%d %H:%M")
                    preview = (rumor.get("content") or "")[:200].replace("\n", " ")
                    dm_previews.append(
                        f"  DM {when}  from {seal['pubkey'][:12]}…  (NIP-17)  {preview!r}"
                    )
            except Exception as exc:  # noqa: BLE001 - not addressed to us / not decryptable / malformed
                ev["_meta"]["note"] = f"gift wrap not unwrapped: {exc.__class__.__name__}: {exc}"

    if dm_previews:
        print("\nDMs:")
        print("\n".join(dm_previews))

    if events:
        os.makedirs(INBOX_DIR, exist_ok=True)
        path = os.path.join(INBOX_DIR, datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".jsonl")
        with open(path, "a") as fh:
            for ev in events:
                fh.write(json.dumps(ev, separators=(",", ":")) + "\n")
        print(f"\nappended {len(events)} event(s) to {path}")
    else:
        print("\nnothing inbound -- identity is reachable but quiet")

    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="look-back window (default 30)")
    ap.add_argument("--timeout", type=float, default=15.0, help="seconds per relay (default 15)")
    args = ap.parse_args()
    try:
        raise SystemExit(asyncio.run(main_async(args)))
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == "__main__":
    main()
