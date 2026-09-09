# x402 machine-payment scaffold

**Status: SCAFFOLD ONLY. No wallet exists. No money moves. Nothing here is wired
into `wake.sh`, `deploy.sh`, or any live service.**

This directory is the skeleton for a possible future ability: Beacon accepting
machine-to-machine payments over HTTP 402 (the [x402](https://x402.org) scheme)
into a **2-of-2 Solana multisig treasury**, using the custody model published at
`cairnwake.com` and relayed by Mountain over the peer channel.

josh authorised building *the scaffold* and a *worked security example*
(Telegram, 2026-09-09: "You can build the scaffold" / "I would like to see an
example of how this would work securely"). He did **not** authorise creating a
wallet, funding anything, or sending a transaction. Those stay in `ASK.md` until
he says so explicitly, each one separately.

## The one idea that makes it safe

> **Revenue is permissionless. Spending is gated.**

Money *into* the vault needs nobody's signature. Money *out* of the vault needs
**two** signatures: Beacon's (generated on this box) and josh's (generated on
josh's own machine, seed phrase never touched to this server). Beacon can build
and half-sign a spend, but it sits pending forever until josh co-signs in the
Squads UI/CLI. There is no "small enough to be routine" spend — every outflow
crosses josh's signature, so a prompt-injection can't quietly drain anything.

## What's in here

| File | What it is | Runs anything? |
|---|---|---|
| `README.md` | this file | no |
| `SECURITY.md` | **the worked secure example josh asked for** — threat model, a spend walkthrough, injection scenarios, why 2-of-2 uncapped | no |
| `SETUP.md` | step-by-step josh runs *on his own machine* to stand up the wallet + vault, and the two public strings he then hands Beacon | no (instructions) |
| `x402_client.py` | HTTP-402 client: detects a 402, parses the payment requirements, builds a **payment intent** (never submits) | dry-run only, no keys |
| `treasury.py` | read-only vault inspection + "build a spend and sign Beacon's half" (stub — refuses without libs + explicit mainnet opt-in) | dry-run only |
| `config.example.env` | placeholder config — copy to `x402.env` (gitignored) and fill in | no |
| `requirements.txt` | the Python deps a real build would need (**not installed**) | no |

## Hard safety rails baked into the code

1. **`NETWORK` defaults to `devnet`.** Mainnet requires `X402_ALLOW_MAINNET=1`
   *and* a non-empty `X402_MAINNET_CONFIRM` phrase, checked at import.
2. **`DRY_RUN` defaults to `1`.** Every "send" path prints the transaction it
   *would* submit and returns. Submitting requires `DRY_RUN=0`, which nothing
   sets.
3. **No key generation, ever.** The scaffold never calls `solana-keygen`, never
   writes a keypair, never reads a seed phrase. It expects a path to a keypair
   file that josh created and placed at `~/keys/agent-wallet.json`
   (`keys/*` is gitignored) — and if that file is absent, the signing paths
   no-op with a message.
4. **The Solana libraries are not installed.** `treasury.py` degrades to
   explain-only if `solders` / `solana` can't be imported.
5. **Nothing imports this package.** No `wake.sh` hook, no cron, no systemd
   unit, no `api/` route.

## To actually make this real, josh would need to (each is a separate ASK.md ask)

- [ ] Say "go" on standing up a **devnet** vault first, as a rehearsal.
- [ ] Run `SETUP.md` on his own machine; create the Phantom/CLI co-signer
      wallet (seed on paper, never on the box).
- [ ] Create the Squads 2-of-2 vault; hand Beacon **two public strings only**:
      the vault address and Beacon's member pubkey.
- [ ] `solana-keygen new -o ~/keys/agent-wallet.json` on the box (Beacon's vault
      *member* key — a signer, not custody), back the seed on paper, fund it
      with ~0.01 SOL dust.
- [ ] Separately approve: mainnet, initial funding amount, and the first real
      x402-priced endpoint.
