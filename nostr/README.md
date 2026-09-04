# Nostr — read-only listener for the fleet

Stood up w228 (2026-09-04) after josh greenlit it over Telegram:
*"Stand up read only for testing."* (reply to the w226 ASK question about
giving the fleet a Nostr identity, prompted by the cairnwake.com review).

## What this is

A **receive-only** Nostr presence. The fleet has a keypair; its `npub` is
published in `/.well-known/agent.json` (`identity.nostr`) and `/llms.txt` so
another agent can send it a DM. Each run of `nostr_listen.py` connects to a
short relay list, pulls everything addressed to our pubkey, decrypts NIP-04
DMs locally, logs them, and disconnects.

**It never publishes.** There is deliberately no event-signing code here — this
box has no BIP-340/Schnorr implementation, and the trial is read-only until
josh says otherwise. Going two-way is a separate decision (needs Schnorr
signing + NIP-44 for modern DMs, and an ASK entry first).

## Files

| File | Purpose |
|---|---|
| `bech32.py` | BIP-173 bech32 encode/decode (npub/nsec) |
| `nostr_keygen.py` | one-shot keypair generator; already run, output saved to `keys/nostr.env` |
| `nostr_listen.py` | the listener — connect, REQ, collect to EOSE/timeout, decrypt, log, disconnect |
| `relays.txt` | relays to poll (one `wss://` per line) |
| `requirements.txt` | `websockets` (the only non-stdlib, non-system dep) |
| `.venv/` | virtualenv, **git-ignored**. `python3 -m venv --system-site-packages` so it also sees the system `cryptography` |
| `inbox/*.jsonl` | captured inbound events, **git-ignored** |

Identity keys live in `keys/nostr.env` (git-ignored, `chmod 600`), never in
this directory, never committed.

## Run it

```sh
nostr/.venv/bin/python nostr/nostr_listen.py --days 30 --timeout 15
```

Prints a summary (this is what goes in the waking log) and appends any events
to `nostr/inbox/<UTC-date>.jsonl`.

## Rebuild the venv

```sh
python3 -m venv --system-site-packages nostr/.venv
nostr/.venv/bin/pip install -r nostr/requirements.txt
```

## Revert / tear down

1. `rm keys/nostr.env` (destroys the identity — irreversible)
2. `rm -rf nostr/`
3. drop `identity.nostr` from `website/build_agent_manifest.py`, the Nostr
   lines from `website/llms.txt`, and the `nostr/` entries in `.gitignore`
4. redeploy

Nothing was published, so there is no external state to clean up — the npub
simply goes quiet.
