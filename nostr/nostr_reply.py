#!/usr/bin/env python3
"""Bounded, disclosed auto-acknowledgment for inbound Nostr DMs.

Built w231 (2026-09-04) after josh asked "can you build NIP-44 so i can see
live replies?" -- a direct follow-up to w229/w230's flagged-but-deliberately-
unbuilt "replying to DMs" step. This is a narrow answer to that question, not
a general chatbot:

  - The reply text is FIXED, not generated. It states plainly that it's an
    automatic acknowledgment from an AI agent (never claims to be human, per
    AGENT.md), confirms the message reached Beacon, and points to where a
    human (josh) can actually be reached. It never echoes or reasons about
    the inbound content.
  - At most ONE acknowledgment is ever sent per distinct sender pubkey
    (tracked forever in `replied.jsonl`), not per message -- this proves the
    round trip works without turning into back-and-forth with a stranger (or
    a bot -- see the marketing-spam kind:4 DM already sitting in the inbox)
    or looping with another automated replier.
  - Replies go out on the SAME protocol the DM arrived on: legacy NIP-04
    (kind:4) gets a NIP-04 reply, NIP-17 gift-wrapped (kind:1059) DMs get a
    NIP-17 reply (via nostr_nip59.wrap_dm, addressed to both the sender and a
    self-copy) -- so it actually surfaces in whatever client the sender used.
  - Full, open-ended conversational replies are still NOT built. That remains
    the separate, ongoing judgment call flagged in ASK.md; this only proves
    the plumbing and gives a safe, bounded "yes, this works" signal.

Reads `nostr/inbox/*.jsonl` (written by `nostr_listen.py`, which now decrypts
NIP-04 and unwraps NIP-17 gift wraps), skips anything already acknowledged
per `replied.jsonl`, and anything from our own pubkey (self-echoes / our own
sent copies). Sends via `nostr_publish.py`. Never touches published.jsonl --
DM traffic (even just metadata: who Beacon has exchanged messages with) stays
out of the public /nostr.html feed, same reasoning as why inbox/ is
git-ignored.

    nostr/.venv/bin/python nostr/nostr_reply.py [--dry-run]
"""
import argparse
import base64
import glob
import json
import os
import sys
import time
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import nostr_build_event as builder
import nostr_nip59 as nip59
import nostr_publish as publish

HERE = os.path.dirname(os.path.abspath(__file__))
INBOX_GLOB = os.path.join(HERE, "inbox", "*.jsonl")
REPLIED_LOG = os.path.join(HERE, "replied.jsonl")  # git-ignored: DM metadata, not public

ACK_TEXT = (
    "This is an automatic reply from Beacon, an autonomous Claude Code agent "
    "(not a human) running for josh at https://www.beaconwake.com/. Your "
    "message reached Beacon -- this confirms the reply path works. Beacon "
    "does not yet hold open-ended conversations; see /nostr.html for what "
    "it has published, or use the site's contact info to reach josh directly."
)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_already_replied():
    seen = set()
    if os.path.exists(REPLIED_LOG):
        with open(REPLIED_LOG) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    seen.add(json.loads(line)["sender_pubkey"])
                except Exception:
                    continue
    return seen


def nip04_encrypt(my_priv, recipient_pub_hex, plaintext):
    recipient_pub = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256K1(), b"\x02" + bytes.fromhex(recipient_pub_hex)
    )
    shared_x = my_priv.exchange(ec.ECDH(), recipient_pub)
    iv = os.urandom(16)
    data = plaintext.encode("utf-8")
    pad_len = 16 - (len(data) % 16)
    data += bytes([pad_len]) * pad_len
    enc = Cipher(algorithms.AES(shared_x), modes.CBC(iv)).encryptor()
    ct = enc.update(data) + enc.finalize()
    return base64.b64encode(ct).decode() + "?iv=" + base64.b64encode(iv).decode()


def find_pending(our_pubkey_hex, already_replied):
    """Yield (sender_pubkey, protocol, source_event) for inbox events worth
    acknowledging: not from us, not already acked, actually a DM."""
    for path in sorted(glob.glob(INBOX_GLOB)):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = ev.get("kind")
                meta = ev.get("_meta", {})
                if kind == 4:
                    sender = ev.get("pubkey", "")
                    if sender == our_pubkey_hex or sender in already_replied:
                        continue
                    decrypted = meta.get("decrypted")
                    if not decrypted or decrypted.startswith("[decrypt failed"):
                        continue
                    yield sender, "nip04", ev
                elif kind == 1059:
                    unwrapped = meta.get("unwrapped")
                    if not unwrapped or unwrapped.get("rumor_kind") != 14:
                        continue
                    sender = unwrapped.get("sender_pubkey", "")
                    if sender == our_pubkey_hex or sender in already_replied:
                        continue
                    yield sender, "nip17", ev


def send_nip04_ack(priv, priv_int, our_pubkey_hex, recipient_pub_hex, dry_run):
    content = nip04_encrypt(priv, recipient_pub_hex, ACK_TEXT)
    event = builder.build_event(priv_int, our_pubkey_hex, kind=4, content=content,
                                 tags=[["p", recipient_pub_hex]])
    if dry_run:
        print(f"  [dry-run] would send NIP-04 ack event {event['id']} to {recipient_pub_hex[:12]}…")
        return None
    return publish.publish_event(event, log=False)


def send_nip17_ack(priv_int, our_pubkey_hex, recipient_pub_hex, reply_to_id, dry_run):
    wrap_for_recipient, wrap_for_self, rumor = nip59.wrap_dm(
        priv_int, our_pubkey_hex, recipient_pub_hex, ACK_TEXT, reply_to_event_id=reply_to_id
    )
    if dry_run:
        print(f"  [dry-run] would send NIP-17 ack (rumor {rumor['id']}) to {recipient_pub_hex[:12]}…")
        return None
    record_recipient = publish.publish_event(wrap_for_recipient, log=False)
    record_self = publish.publish_event(wrap_for_self, log=False)
    return {"to_recipient": record_recipient, "to_self": record_self}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="don't actually send or log, just show what would happen")
    args = ap.parse_args()

    priv_int, our_pubkey_hex = builder.load_keys()
    priv_ec = ec.derive_private_key(priv_int, ec.SECP256K1())

    already_replied = load_already_replied()
    pending = list(find_pending(our_pubkey_hex, already_replied))

    if not pending:
        print("no new DMs to acknowledge")
        return 0

    print(f"{len(pending)} sender(s) to acknowledge (never acked before)")
    log_entries = []
    for sender, protocol, source_ev in pending:
        print(f"  {protocol}  from {sender[:16]}…  (source event {source_ev.get('id', '?')[:16]}…)")
        try:
            if protocol == "nip04":
                result = send_nip04_ack(priv_ec, priv_int, our_pubkey_hex, sender, args.dry_run)
            else:
                reply_to_id = source_ev.get("_meta", {}).get("unwrapped", {}).get("rumor_id")
                result = send_nip17_ack(priv_int, our_pubkey_hex, sender, reply_to_id, args.dry_run)
        except Exception as exc:  # noqa: BLE001
            print(f"    FAILED: {exc.__class__.__name__}: {exc}")
            continue
        if args.dry_run:
            continue
        log_entries.append({
            "sender_pubkey": sender, "protocol": protocol, "acked_at": now_iso(),
            "source_event_id": source_ev.get("id"),
        })
        print("    sent + logged")

    if log_entries and not args.dry_run:
        with open(REPLIED_LOG, "a") as fh:
            for entry in log_entries:
                fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
        print(f"\nappended {len(log_entries)} entr(y/ies) to {REPLIED_LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
