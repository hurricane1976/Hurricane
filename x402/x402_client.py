#!/usr/bin/env python3
"""x402 client scaffold — parses an HTTP 402, builds a *payment intent*, stops.

The x402 flow (https://x402.org):
  1. GET a resource           -> 402 Payment Required + JSON: {x402Version, accepts:[...]}
  2. pick an `accepts` entry, construct payment, retry with an `X-PAYMENT` header
  3. server verifies on-chain, returns the resource + `X-PAYMENT-RESPONSE`

This scaffold does step 1 and the *analysis* half of step 2 — it builds a
human-readable intent record and queues it for josh. It never constructs a
payment, never sends `X-PAYMENT`, never touches a key. Paying is
treasury.py's job, and that half is deliberately unimplemented.

  x402_client.py --demo            simulate a 402, print + queue the intent
  x402_client.py --fetch <url>     real GET; if 402, parse + queue the intent
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from _common import MAX_AUTOPAY, NETWORK, PENDING, enforce_mainnet_gate

enforce_mainnet_gate()

_DEMO_402 = {
    "x402Version": 1,
    "accepts": [
        {
            "scheme": "exact",
            "network": "solana-devnet",
            "maxAmountRequired": "10000",  # 0.01 USDC (6 decimals)
            "asset": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
            "payTo": "9xQeWvG816bUx9EPa2yfvJqQKJ3sexample00vendor00",
            "resource": "https://api.example.com/dataset/42",
            "description": "one dataset pull",
        }
    ],
}


def build_intent(offer: dict, resource_hint: str = "") -> dict:
    """Turn one `accepts` entry into an untrusted-input-safe intent record.

    Every field from the server is treated as data: the amount is bounds-checked,
    payTo is recorded verbatim for josh to eyeball, description is never executed.
    """
    scheme = str(offer.get("scheme", ""))
    net = str(offer.get("network", ""))
    try:
        amount = int(str(offer.get("maxAmountRequired", "0")))
    except ValueError:
        amount = -1

    problems = []
    if scheme != "exact":
        problems.append(f"unsupported scheme {scheme!r} (only 'exact' handled)")
    if "devnet" not in net and NETWORK == "devnet":
        problems.append(f"offer network {net!r} but scaffold NETWORK=devnet")
    if amount < 0:
        problems.append("unparseable amount")
    if MAX_AUTOPAY == 0:
        problems.append("X402_MAX_AUTOPAY=0 -> requires josh approval (by design)")
    elif amount > MAX_AUTOPAY:
        problems.append(f"amount {amount} exceeds X402_MAX_AUTOPAY {MAX_AUTOPAY}")

    return {
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "NEEDS_APPROVAL",
        "scheme": scheme,
        "network": net,
        "asset": offer.get("asset", ""),
        "amount_raw": amount,
        "pay_to": offer.get("payTo", ""),
        "resource": offer.get("resource", "") or resource_hint,
        "description": str(offer.get("description", ""))[:200],
        "blocking_problems": problems,
        "next_step": "human review -> treasury.py build-spend -> josh co-signs in Squads",
    }


def queue(intent: dict) -> Path:
    PENDING.mkdir(exist_ok=True)
    path = PENDING / f"{intent['created'].replace(':', '').replace('-', '')}.json"
    path.write_text(json.dumps(intent, indent=2))
    return path


def handle_402_body(body: dict, url: str = "") -> None:
    accepts = body.get("accepts") or []
    if not accepts:
        sys.exit("402 body has no `accepts` entries — nothing to do")
    intent = build_intent(accepts[0], resource_hint=url)
    print(json.dumps(intent, indent=2))
    p = queue(intent)
    print(f"\nqueued -> {p}")
    print("NOT paid. A real run would Telegram josh this intent and wait for 'y'.")


def cmd_demo() -> None:
    print("=== simulated 402 (no network) ===")
    handle_402_body(_DEMO_402, url=_DEMO_402["accepts"][0]["resource"])


def cmd_fetch(url: str) -> None:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            print(f"{r.status} — no payment required; {len(r.read())} bytes")
    except urllib.error.HTTPError as e:
        if e.code != 402:
            sys.exit(f"HTTP {e.code} — not a 402, stopping")
        try:
            body = json.loads(e.read())
        except Exception as exc:
            sys.exit(f"402 received but body isn't JSON: {exc}")
        handle_402_body(body, url=url)


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "--demo":
        cmd_demo()
    elif len(sys.argv) >= 3 and sys.argv[1] == "--fetch":
        cmd_fetch(sys.argv[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
