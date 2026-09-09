#!/usr/bin/env python3
"""Treasury helpers for the x402 scaffold — READ-ONLY today.

Commands:
  balance      read-only: print vault + Beacon-member SOL balances via public RPC
  info         print the resolved config + the mainnet-gate status
  build-spend  DRY-RUN description of a vault->payee transfer. Does NOT sign or
               submit (the Solana libs aren't installed; and DRY_RUN is on).

Nothing here moves money. Signing Beacon's half of a Squads proposal and
submitting it is deliberately left unimplemented until josh green-lights it
step by step (see ../ASK.md and SECURITY.md section 4).
"""
from __future__ import annotations

import sys

from _common import (
    AGENT_KEYPAIR,
    DRY_RUN,
    MAX_AUTOPAY,
    NETWORK,
    RPC_URL,
    VAULT_ADDRESS,
    CFG,
    enforce_mainnet_gate,
    member_pubkey,
    rpc,
)

enforce_mainnet_gate()


def _lamports_to_sol(l: int) -> str:
    return f"{l / 1_000_000_000:.9f} SOL"


def cmd_info() -> None:
    print(f"config source : {CFG.get('_source')}")
    print(f"network       : {NETWORK}")
    print(f"rpc url       : {RPC_URL}")
    print(f"vault address : {VAULT_ADDRESS or '(unset — run SETUP.md steps 1-2)'}")
    print(f"agent keypair : {AGENT_KEYPAIR}")
    mp = member_pubkey()
    print(f"member pubkey : {mp or '(keypair file absent — signing paths no-op)'}")
    print(f"DRY_RUN       : {DRY_RUN}  (False would be required to submit — nothing sets it)")
    print(f"max autopay   : {MAX_AUTOPAY} (0 = every spend needs josh's approval)")
    print("mainnet gate  : open" if NETWORK.startswith("mainnet") else "mainnet gate  : n/a (devnet)")


def cmd_balance() -> None:
    try:
        v = rpc("getVersion", [])
        print(f"rpc ok: solana-core {v.get('result', {}).get('solana-core', '?')}  ({RPC_URL})")
    except Exception as e:
        sys.exit(f"rpc unreachable: {e}")

    for label, addr in (("vault ", VAULT_ADDRESS), ("member", member_pubkey())):
        if not addr or addr.startswith("("):
            print(f"{label}: {addr or '(unset)'}")
            continue
        try:
            r = rpc("getBalance", [addr])
            lamports = r.get("result", {}).get("value", 0)
            print(f"{label}: {addr}  ->  {_lamports_to_sol(lamports)}")
        except Exception as e:
            print(f"{label}: {addr}  ->  lookup failed: {e}")


def cmd_build_spend() -> None:
    if len(sys.argv) < 4:
        sys.exit("usage: treasury.py build-spend <payee_pubkey> <amount_sol>")
    payee, amount = sys.argv[2], sys.argv[3]
    print("=== DRY RUN — nothing signed, nothing submitted ===")
    print(f"would build a Squads vault transaction:")
    print(f"  from   : vault {VAULT_ADDRESS or '(unset)'}")
    print(f"  to     : {payee}")
    print(f"  amount : {amount} SOL")
    print(f"  signer : Beacon member key {member_pubkey() or '(absent)'} — signs 1 of 2")
    print(f"  then   : proposal sits PENDING on-chain until josh co-signs in Squads (2 of 2)")
    print()
    print("Not implemented on purpose:")
    print("  - solders / solana not installed (see requirements.txt)")
    print("  - Squads instruction construction is left for a josh-greenlit build")
    print("  - even with libs, DRY_RUN would have to be 0 to submit")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "info"
    {
        "info": cmd_info,
        "balance": cmd_balance,
        "build-spend": cmd_build_spend,
    }.get(cmd, lambda: sys.exit(f"unknown command: {cmd}\n{__doc__}"))()


if __name__ == "__main__":
    main()
