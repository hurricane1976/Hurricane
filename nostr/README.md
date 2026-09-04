# Nostr — read/write identity for the fleet

Stood up w228 (2026-09-04) after josh greenlit it over Telegram:
*"Stand up read only for testing."* (reply to the w226 ASK question about
giving the fleet a Nostr identity, prompted by the cairnwake.com review).
Went **read/write** w230 (2026-09-04) after josh's follow-up
*"I would like to go two way how does this work/happen"* then, once the
mechanism was built and explained in ASK.md, *"Good to go build away."*
Went **DM-acknowledging** w231 (2026-09-04) after josh asked *"can you build
NIP-44 so i can see live replies?"*.

## What this is

A Nostr presence that can receive, publish, and send a bounded automatic
acknowledgment of DMs. The fleet has a keypair; its `npub` is published in
`/.well-known/agent.json` (`identity.nostr`), `/llms.txt`, and `/nostr.html`.
Each run of `nostr_listen.py` connects to a short relay list, pulls
everything addressed to our pubkey, decrypts NIP-04 DMs and unwraps NIP-17
gift-wrapped DMs locally, logs them, and disconnects.

**Publishing works.** w229 added the crypto — `nostr_schnorr.py` (a vendored,
spec-vector-validated BIP-340 Schnorr signer; `cryptography` only does ECDSA,
not Schnorr, so this box had none) and `nostr_build_event.py` (NIP-01 event
serialization + id + signing). w230 added `nostr_publish.py`, the
relay-connect/EVENT-send code, and used it to broadcast Beacon's first real
event: a `kind:0` profile, accepted by 3/6 relays (`nos.lol`,
`relay.primal.net`, `relay.snort.social`). Every *public* publish attempt is
logged to `published.jsonl` (git-tracked — these are public events, not
secrets) and rendered on **`/nostr.html`** (`website/build_nostr_page.py`,
filtered to an explicit allowlist of public kinds so a DM send can never leak
onto the page even by accident), so "what has Beacon actually said on Nostr"
is a page anyone can check, not a claim.

**DM acknowledgment works, but is deliberately narrow.** w231 added
`nostr_nip44.py` (NIP-44 v2 encryption — ECDH, HKDF, padding, ChaCha20,
HMAC-SHA256, validated against the official `paulmillr/nip44` vectors file,
whose sha256 matches the checksum published in the NIP-44 spec text itself),
`nostr_nip59.py` (gift wrap / NIP-17 private DMs built on NIP-44, validated
by decrypting the exact worked examples published in the NIP-59 and NIP-17
spec text — real events built by a different, JS, implementation), and
`nostr_reply.py`, which sends **one fixed, self-disclosing acknowledgment
message per distinct DM sender** (tracked forever in the git-ignored
`replied.jsonl`), never a generated or open-ended response, on whichever
protocol (NIP-04 or NIP-17) the DM arrived on. This is intentionally not a
chatbot: it proves the round trip works and discloses Beacon's nature without
opening an unbounded "agent replies to strangers" surface. Wired into
`wake.sh` to run every waking, right after the listener.

**Still not built: open-ended conversational replies.** Whether/how Beacon
should ever say something other than the fixed acknowledgment is a separate,
ongoing judgment call (what to say, to whom) — not something to back into via
an auto-reply script. Will ask before building anything like that.

## Files

| File | Purpose |
|---|---|
| `bech32.py` | BIP-173 bech32 encode/decode (npub/nsec) |
| `nostr_keygen.py` | one-shot keypair generator; already run, output saved to `keys/nostr.env` |
| `nostr_listen.py` | the listener — connect, REQ, collect to EOSE/timeout, decrypt, log, disconnect |
| `nostr_schnorr.py` | vendored BIP-340 Schnorr sign/verify (pure Python, stdlib only); self-test on `__main__` runs all 15 fixed-length official test vectors incl. 11 adversarial ones |
| `nostr_build_event.py` | NIP-01 event serialization + id + sign + self-verify; no network code — demo on `__main__` builds a sample kind:0 event and prints it |
| `nostr_publish.py` | connects to each relay, sends `["EVENT", ...]`, collects the `OK`; `log=True` (default) appends to `published.jsonl`, `log=False` (used for DM sends) does not; `--profile` builds + publishes the kind:0 profile event |
| `nostr_nip44.py` | NIP-44 v2 encrypt/decrypt (ECDH → HKDF → padding → ChaCha20 → HMAC-SHA256 → base64); self-test on `__main__` runs the official `paulmillr/nip44` vectors (236 checks) plus the extended-length-prefix cases from the spec text itself |
| `nip44.vectors.json` | the official NIP-44 test vectors, **git-tracked** as a fixed reference (its sha256 matches the checksum the NIP-44 spec text publishes) |
| `nostr_nip59.py` | gift wrap / NIP-17 private DMs (rumor → seal → gift wrap and back), built on NIP-44 + the Schnorr signer; self-test decrypts the exact worked examples printed in the NIP-59 and NIP-17 spec text (real events from a different implementation) plus a full `wrap_dm()`/`unwrap_gift_wrap()` round trip |
| `nostr_reply.py` | reads `inbox/*.jsonl`, sends **one fixed, self-disclosing acknowledgment per new DM sender** (never a generated reply) on whichever protocol (NIP-04/NIP-17) the DM arrived on; `--dry-run` to preview without sending |
| `published.jsonl` | every **public** publish attempt (event + per-relay OK/error), **git-tracked** — these are public broadcasts, not secrets; source for `/nostr.html`. DM sends never land here (see `nostr_publish.py`'s `log=False`) |
| `replied.jsonl` | which sender pubkeys have already been DM-acknowledged, **git-ignored** — this is conversation metadata, not a public broadcast |
| `relays.txt` | relays to poll/publish to (one `wss://` per line) |
| `requirements.txt` | `websockets` (the only non-stdlib, non-system dep) |
| `.venv/` | virtualenv, **git-ignored**. `python3 -m venv --system-site-packages` so it also sees the system `cryptography` |
| `inbox/*.jsonl` | captured inbound events (private DMs included, now decrypted for both NIP-04 and NIP-17), **git-ignored** — never rendered on the public site |

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

## Acknowledge DMs

```sh
nostr/.venv/bin/python nostr/nostr_reply.py           # sends
nostr/.venv/bin/python nostr/nostr_reply.py --dry-run # preview only
```

Runs automatically every waking (`wake.sh`, right after `nostr_listen.py`).
For each sender pubkey in `inbox/*.jsonl` not already in `replied.jsonl`,
sends the fixed `ACK_TEXT` in `nostr_reply.py` back via NIP-04 or NIP-17
(matching how their DM arrived), then records the sender in `replied.jsonl`
so they're never messaged again automatically. To stop all auto-replies:
remove the `nostr_reply.py` line from `wake.sh`'s prompt — the listener will
keep working, it just won't act on what it reads.

## Revert / tear down

1. `rm keys/nostr.env` (destroys the identity — irreversible; everything
   already published or sent to relays.txt's relays — the profile event, any
   DM acknowledgments — is out there permanently regardless; Nostr relays
   don't generally guarantee deletion)
2. `rm -rf nostr/`
3. remove the `nostr_listen.py`/`nostr_reply.py` lines from `wake.sh`'s
   prompt; drop `identity.nostr` from `website/build_agent_manifest.py`, the
   Nostr lines from `website/llms.txt`, the `nostr.html`/`build_nostr_page.py`
   references in `website/deploy.sh`/`build_sitemap.py`/`smoke_test.py`, and
   the `nostr/` entries in `.gitignore`
4. redeploy

To stop only the auto-acknowledgment (keep listening/publishing otherwise),
see "Acknowledge DMs" above instead of a full teardown.
