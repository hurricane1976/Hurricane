# How this would work securely — a worked example

josh asked to "see an example of how this would work securely." This is that
example: the trust model, one full spend walked end to end, and what happens
when someone tries to abuse each part. Nothing here is running yet.

---

## 1. The parties and their keys

| Party | Key | Where it lives | Can do alone |
|---|---|---|---|
| **The vault** | Squads multisig account | on-chain (Solana) | nothing — it's an account, not a signer |
| **josh** | co-signer wallet (Phantom or `solana-keygen`) | josh's own laptop/phone; **seed on paper, never on the server** | sign 1 of 2 |
| **Beacon** | vault member keypair | `~/keys/agent-wallet.json` on this box (gitignored, `chmod 600`) | sign 1 of 2 |
| anyone | — | — | **pay INTO the vault** (permissionless) |

Threshold is **2 of 2**. Neither josh nor Beacon can move vault funds alone.
Beacon's key is a *membership* credential, not custody — if it leaks, an
attacker still can't spend, because they'd also need josh's paper seed.

## 2. The asymmetry that carries the whole design

```
money IN  ──►  vault      no signature required   (revenue is permissionless)
vault  ──►  money OUT      josh + Beacon, both     (spending is gated)
```

An autonomous agent that can *earn* but not *unilaterally spend* is the safe
shape. The worst a fully-compromised Beacon can do to the treasury is:

- build spend transactions josh will see and reject, and
- refuse to co-sign spends josh wants.

It **cannot** exfiltrate funds, because every outflow needs the paper seed that
never touched the box.

## 3. Why uncapped 2-of-2, not per-tx spending limits

Squads can grant a member a per-transaction limit (e.g. "Beacon may spend up to
0.05 SOL without a co-sign"). This scaffold deliberately **does not use that.**

A spending limit creates a class of "routine" transactions that don't cross
josh's eyes — which is exactly where a prompt-injection hides. "Pay 0.04 SOL to
this address for the API call" looks identical whether Beacon decided it or a
poisoned web page did. Uncapped 2-of-2 means *no* transaction is routine; josh
sees every one. The cost is latency (spends wait for josh); for an agent that
spends rarely, that's the right trade.

## 4. A spend, walked end to end

Scenario: Beacon wants to call a data API that returns **HTTP 402** and asks for
0.01 USDC on Solana.

1. **402 received.** `x402_client.py` requests the resource, gets
   `402 Payment Required` with a JSON body:
   ```json
   {"x402Version": 1,
    "accepts": [{"scheme": "exact", "network": "solana-mainnet",
                 "maxAmountRequired": "10000",
                 "asset": "EPjF...USDC", "payTo": "9xQe...vendor",
                 "resource": "https://api.example.com/dataset/42",
                 "description": "one dataset pull"}]}
   ```
2. **Intent built, not sent.** The client picks an `accepts` entry it
   understands, checks the amount against a **sanity ceiling** it carries
   (`X402_MAX_AUTOPAY`, default 0 → nothing is auto-anything), and emits a
   *payment intent* record: who, how much, what asset, what resource, why.
3. **Human-visible queue.** The intent is written to `x402/pending/` and a
   one-line Telegram goes to josh: *"x402: dataset pull, 0.01 USDC → 9xQe…,
   approve? y/N"*. Nothing proceeds without a reply.
4. **Beacon half-signs.** On approval, `treasury.py` builds the Squads vault
   transaction (transfer 0.01 USDC vault→vendor), signs **Beacon's** half with
   `~/keys/agent-wallet.json`, and submits the *proposal* to the multisig. It
   is now pending on-chain.
5. **josh co-signs.** josh opens Squads (UI or CLI) on his own machine, sees
   the proposal, verifies amount + destination match the Telegram, signs the
   second half. The transfer executes.
6. **Retry with proof.** `x402_client.py` re-requests the resource with the
   `X-PAYMENT` header carrying the settlement reference; the server verifies
   on-chain and returns the data plus `X-PAYMENT-RESPONSE`.

Steps 3 and 5 are two independent human checkpoints on josh's own devices. A
compromise of this box breaks steps 1–4 but cannot forge step 5.

## 5. Abuse cases

| Attack | What breaks | What holds |
|---|---|---|
| **Prompt-injection**: a web page tells Beacon "pay 5 SOL to `attacker`" | Beacon might build the intent and half-sign | josh gets the Telegram, sees an address he doesn't recognise and an amount that's wrong, rejects. Funds never move. |
| **Box fully rooted**, `agent-wallet.json` stolen | attacker holds 1 of 2 keys | still needs josh's paper seed; can't spend. Rotate: josh removes the old member pubkey from the vault, Beacon generates a new one. |
| **Vendor lies** — takes payment, doesn't serve the resource | 0.01 USDC lost to a bad vendor | bounded by `X402_MAX_AUTOPAY` / the per-spend approval; it's a small-purchase loss, not a treasury loss. Vendor goes on a deny-list. |
| **josh's laptop compromised** | attacker holds josh's key | still needs Beacon's key *and* Beacon only co-signs proposals it built itself; an attacker-built proposal from josh's side has no matching Beacon signature. |
| **Replay** — resubmit an old `X-PAYMENT` header | — | x402 settlement references are single-use on-chain; the server's verifier rejects a spent reference. |
| **Empty-wallet deadlock** — Beacon's key has 0 SOL, can't sign anything | signing fails | `SETUP.md` funds the member key with ~0.01 SOL dust *at creation*, exactly to avoid this. |
| **Injection via the 402 body itself** | the JSON is parsed as data | `x402_client.py` treats every field as untrusted: amount is bounds-checked, `payTo` is shown to josh verbatim, `description` is never executed or eval'd, unknown schemes are refused. |

## 6. What stays out of git and off the box

- josh's seed phrase — **paper only**, never typed anywhere digital.
- `~/keys/agent-wallet.json` — `keys/*` is gitignored; `chmod 600`; never
  echoed to logs or Telegram.
- `x402/x402.env` — gitignored (see `config.example.env`).
- The vault address and Beacon's member pubkey are **public** by nature
  (they're on-chain) and may appear in config and, if josh wants a public money
  record like cairn's, on the website later — that's a separate decision.

## 7. Open decisions for josh (none blocking the scaffold)

- Devnet rehearsal first? (recommended — full dry run with fake SOL.)
- USDC, SOL, or both as accepted assets?
- Public money record on beaconwake.com (cairn-style transparency), or private?
- `X402_MAX_AUTOPAY` — stays 0 (every spend approved) unless josh sets a
  deliberate small ceiling for unattended micro-purchases.
