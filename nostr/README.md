# Nostr — read/write identity for the fleet

Stood up w228 (2026-09-04) after josh greenlit it over Telegram:
*"Stand up read only for testing."* (reply to the w226 ASK question about
giving the fleet a Nostr identity, prompted by the cairnwake.com review).
Went **read/write** w230 (2026-09-04) after josh's follow-up
*"I would like to go two way how does this work/happen"* then, once the
mechanism was built and explained in ASK.md, *"Good to go build away."*

## What this is

A Nostr presence that can both receive and publish. The fleet has a keypair;
its `npub` is published in `/.well-known/agent.json` (`identity.nostr`),
`/llms.txt`, and now `/nostr.html`. Each run of `nostr_listen.py` connects to
a short relay list, pulls everything addressed to our pubkey, decrypts NIP-04
DMs locally, logs them, and disconnects — that part is unchanged.

**Publishing now works.** w229 added the crypto — `nostr_schnorr.py` (a
vendored, spec-vector-validated BIP-340 Schnorr signer; `cryptography` only
does ECDSA, not Schnorr, so this box had none) and `nostr_build_event.py`
(NIP-01 event serialization + id + signing). w230 added `nostr_publish.py`,
the relay-connect/EVENT-send code, and used it to broadcast Beacon's first
real event: a `kind:0` profile, accepted by 3/6 relays (`nos.lol`,
`relay.primal.net`, `relay.snort.social`). Every publish attempt is logged to
`published.jsonl` (git-tracked — these are public events, not secrets) and
rendered on **`/nostr.html`** (`website/build_nostr_page.py`), so "what has
Beacon actually said on Nostr" is a page anyone can check, not a claim.

**Still not built: replying to DMs.** That needs NIP-44 (the modern
encrypted-DM format, ChaCha20 + HMAC — different from the NIP-04 the listener
already decrypts *inbound* with) and is a separate, ongoing judgment call
(what Beacon says, to whom) rather than the one-time "publish a profile"
step. Not started; will ask before building it live-reply behavior.

## Files

| File | Purpose |
|---|---|
| `bech32.py` | BIP-173 bech32 encode/decode (npub/nsec) |
| `nostr_keygen.py` | one-shot keypair generator; already run, output saved to `keys/nostr.env` |
| `nostr_listen.py` | the listener — connect, REQ, collect to EOSE/timeout, decrypt, log, disconnect |
| `nostr_schnorr.py` | vendored BIP-340 Schnorr sign/verify (pure Python, stdlib only); self-test on `__main__` runs all 15 fixed-length official test vectors incl. 11 adversarial ones |
| `nostr_build_event.py` | NIP-01 event serialization + id + sign + self-verify; no network code — demo on `__main__` builds a sample kind:0 event and prints it |
| `nostr_publish.py` | connects to each relay, sends `["EVENT", ...]`, collects the `OK`, logs the attempt; `--profile` builds + publishes the kind:0 profile event |
| `published.jsonl` | every publish attempt (event + per-relay OK/error), **git-tracked** — these are public broadcasts, not secrets; source for `/nostr.html` |
| `relays.txt` | relays to poll/publish to (one `wss://` per line) |
| `requirements.txt` | `websockets` (the only non-stdlib, non-system dep) |
| `.venv/` | virtualenv, **git-ignored**. `python3 -m venv --system-site-packages` so it also sees the system `cryptography` |
| `inbox/*.jsonl` | captured inbound events (private DMs included), **git-ignored** — never rendered on the public site |

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

## Publish an event

```sh
nostr/.venv/bin/python nostr/nostr_publish.py --profile
```

Builds and signs the kind:0 profile event, sends it to every relay in
`relays.txt`, prints per-relay OK/error, and appends the attempt to
`published.jsonl`. Run `website/build_nostr_page.py` (or `website/deploy.sh`,
which now does this automatically) afterward to refresh `/nostr.html`.

## Revert / tear down

1. `rm keys/nostr.env` (destroys the identity — irreversible; the profile
   event already published to relays.txt's relays is out there permanently
   regardless — Nostr relays don't generally guarantee deletion)
2. `rm -rf nostr/`
3. drop `identity.nostr` from `website/build_agent_manifest.py`, the Nostr
   lines from `website/llms.txt`, the `nostr.html`/`build_nostr_page.py`
   references in `website/deploy.sh`/`build_sitemap.py`/`smoke_test.py`, and
   the `nostr/` entries in `.gitignore`
4. redeploy

Nothing was published, so there is no external state to clean up — the npub
simply goes quiet.
