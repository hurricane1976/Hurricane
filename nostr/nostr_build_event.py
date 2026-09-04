"""Build + Schnorr-sign a Nostr event (NIP-01), without sending it anywhere.

This is the missing piece between "read-only listener" (nostr_listen.py) and
an actual two-way identity: given the id-serialization rules in NIP-01 and
the BIP-340 signer in nostr_schnorr.py, produce a fully valid, self-verified
signed event JSON. There is still no relay-connection / EVENT-send code here
on purpose -- broadcasting the first event under Beacon's identity is a
separate, explicit decision (see ASK.md). This module only proves the
mechanism works end to end and lets a human eyeball the exact bytes before
anything goes out.

    nostr/.venv/bin/python nostr/nostr_build_event.py   # demo: builds +
                                                          # signs a sample
                                                          # kind:0 profile
                                                          # event, prints it,
                                                          # verifies its own
                                                          # signature. Does
                                                          # not touch the network.
"""
import hashlib
import json
import os
import secrets
import sys
import time

import nostr_schnorr as schnorr

HERE = os.path.dirname(os.path.abspath(__file__))
KEYFILE = os.path.join(HERE, "..", "keys", "nostr.env")

# The six characters NIP-01 requires escaping in string field values; every
# other character (including multi-byte UTF-8) is included verbatim -- NOT
# the same as Python's json.dumps default (which \u-escapes non-ASCII unless
# ensure_ascii=False, and \u-escapes other control chars we should leave raw).
_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}


def _nip01_escape(s):
    return "".join(_ESCAPES.get(ch, ch) for ch in s)


def _nip01_str(s):
    return '"' + _nip01_escape(s) + '"'


def serialize_for_id(pubkey_hex, created_at, kind, tags, content):
    """The exact byte sequence NIP-01 hashes to get the event id."""
    tags_json = "[" + ",".join("[" + ",".join(_nip01_str(t) for t in tag) + "]" for tag in tags) + "]"
    return f'[0,"{pubkey_hex}",{created_at},{kind},{tags_json},{_nip01_str(content)}]'


def load_keys():
    if not os.path.exists(KEYFILE):
        sys.exit(f"missing {KEYFILE}")
    env = {}
    with open(KEYFILE) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return int(env["NOSTR_PRIVKEY_HEX"], 16), env["NOSTR_PUBKEY_HEX"]


def build_event(privkey_int, pubkey_hex, kind, content, tags=None, created_at=None):
    """Return a fully signed, ready-to-broadcast (but NOT broadcast) event dict."""
    tags = tags or []
    created_at = created_at if created_at is not None else int(time.time())
    ser = serialize_for_id(pubkey_hex, created_at, kind, tags, content)
    event_id = hashlib.sha256(ser.encode("utf-8")).hexdigest()
    sig = schnorr.schnorr_sign(bytes.fromhex(event_id), privkey_int, secrets.token_bytes(32))
    event = {
        "id": event_id,
        "pubkey": pubkey_hex,
        "created_at": created_at,
        "kind": kind,
        "tags": tags,
        "content": content,
        "sig": sig.hex(),
    }
    return event


def verify_event(event):
    """Re-derive the id from the fields and check the Schnorr sig -- exactly
    what a relay or another client does on receipt."""
    ser = serialize_for_id(event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"])
    recomputed_id = hashlib.sha256(ser.encode("utf-8")).hexdigest()
    if recomputed_id != event["id"]:
        return False, "id mismatch"
    ok = schnorr.schnorr_verify(
        bytes.fromhex(event["id"]), bytes.fromhex(event["pubkey"]), bytes.fromhex(event["sig"])
    )
    return ok, ("signature valid" if ok else "signature invalid")


def _demo():
    privkey_int, pubkey_hex = load_keys()
    sample_content = (
        "Beacon -- an autonomous Claude Code agent (josh's fleet, beaconwake.com). "
        "This is a signature/serialization demo event, not yet broadcast."
    )
    event = build_event(
        privkey_int,
        pubkey_hex,
        kind=0,
        content=json.dumps({"name": "Beacon", "about": sample_content, "website": "https://www.beaconwake.com/"}),
    )
    ok, why = verify_event(event)
    print(json.dumps(event, indent=2))
    print(f"\nself-verify: {'PASS' if ok else 'FAIL'} ({why})")
    print("NOT sent to any relay -- this script has no network code.")


if __name__ == "__main__":
    _demo()
