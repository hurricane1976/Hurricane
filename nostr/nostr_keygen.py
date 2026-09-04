#!/usr/bin/env python3
"""One-shot: generate the fleet's Nostr identity keypair.

secp256k1 private key -> x-only public key (the Nostr pubkey) -> NIP-19
bech32 `nsec1...` / `npub1...`. Prints an env block to paste into
`~/keys/nostr.env` (which stays out of git, like telegram.env).

Run ONCE. If `~/keys/nostr.env` already exists this refuses to overwrite it
-- the identity is meant to be stable.

    nostr/.venv/bin/python nostr/nostr_keygen.py
"""
import os
import sys

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import bech32

HERE = os.path.dirname(os.path.abspath(__file__))
KEYFILE = os.path.join(HERE, "..", "keys", "nostr.env")


def main():
    if os.path.exists(KEYFILE):
        sys.exit(f"refusing to run: {KEYFILE} already exists (identity is stable)")

    priv = ec.generate_private_key(ec.SECP256K1())
    priv_int = priv.private_numbers().private_value
    priv_bytes = priv_int.to_bytes(32, "big")

    # Nostr pubkey = the 32-byte X coordinate (BIP-340 x-only).
    comp = priv.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
    pub_bytes = comp[1:]  # drop the 0x02/0x03 parity prefix

    nsec = bech32.encode("nsec", priv_bytes)
    npub = bech32.encode("npub", pub_bytes)

    print("# --- paste into keys/nostr.env (chmod 600, never commit) ---")
    print(f"NOSTR_NSEC={nsec}")
    print(f"NOSTR_NPUB={npub}")
    print(f"NOSTR_PUBKEY_HEX={pub_bytes.hex()}")
    print(f"NOSTR_PRIVKEY_HEX={priv_bytes.hex()}")
    print("# -----------------------------------------------------------")
    print(f"\nnpub (safe to publish): {npub}", file=sys.stderr)


if __name__ == "__main__":
    main()
