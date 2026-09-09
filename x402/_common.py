"""Shared config + guards for the x402 scaffold. Pure stdlib. Inert.

Loading this module never touches the network and never touches a key. It only
reads an env file and enforces the mainnet safety gate.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PENDING = HERE / "pending"


def _load_env() -> dict:
    """x402/x402.env if present, else config.example.env. `KEY=value` lines."""
    for name in ("x402.env", "config.example.env"):
        p = HERE / name
        if p.exists():
            env = {}
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
            env["_source"] = name
            return env
    return {"_source": "(none)"}


CFG = _load_env()


def cfg(key: str, default: str = "") -> str:
    # process env wins over the file, so a one-off run can override
    return os.environ.get(key, CFG.get(key, default))


NETWORK = cfg("NETWORK", "devnet")
RPC_URL = cfg("RPC_URL", "https://api.devnet.solana.com")
VAULT_ADDRESS = cfg("VAULT_ADDRESS", "")
AGENT_KEYPAIR = cfg("AGENT_KEYPAIR", "/home/agent/keys/agent-wallet.json")
DRY_RUN = cfg("DRY_RUN", "1") != "0"
MAX_AUTOPAY = int(cfg("X402_MAX_AUTOPAY", "0") or "0")


def enforce_mainnet_gate() -> None:
    """A real mainnet run needs two deliberate switches. Anything else -> stop."""
    if NETWORK not in ("mainnet", "mainnet-beta"):
        return
    allow = cfg("X402_ALLOW_MAINNET", "0") == "1"
    confirm = cfg("X402_MAINNET_CONFIRM", "").strip()
    if not (allow and confirm):
        sys.exit(
            "REFUSING: NETWORK=%s but the mainnet gate is closed.\n"
            "  Set X402_ALLOW_MAINNET=1 AND X402_MAINNET_CONFIRM=<phrase> to arm it.\n"
            "  (Devnet rehearsal first — see SETUP.md.)" % NETWORK
        )


# --- tiny base58 (encode only) so we can show the member pubkey without deps ---
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    pad = len(raw) - len(raw.lstrip(b"\x00"))
    return "1" * pad + out


def member_pubkey() -> str | None:
    """Derive Beacon's vault member pubkey from a `solana-keygen` JSON keypair.

    That format is a 64-int JSON array: bytes[0:32] secret, bytes[32:64] public.
    We read ONLY bytes[32:64]. If the file is absent, return None (signing
    paths no-op).
    """
    p = Path(AGENT_KEYPAIR)
    if not p.exists():
        return None
    try:
        arr = json.loads(p.read_text())
        if isinstance(arr, list) and len(arr) == 64:
            return b58encode(bytes(arr[32:64]))
    except Exception:
        pass
    return "(unreadable keypair file)"


def rpc(method: str, params: list) -> dict:
    """Minimal read-only Solana JSON-RPC over urllib. Used only for getBalance /
    getVersion — never for sending a transaction."""
    import urllib.request

    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode()
    req = urllib.request.Request(
        RPC_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())
