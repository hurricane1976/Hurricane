# Setup — what josh runs, and in what order

**Do not start this until you've decided you want it.** Every step is reversible
only up to the point money goes in. Recommended: do the whole thing on
**devnet** first (free SOL from a faucet), tear it down, then repeat on mainnet.

Beacon does **none** of steps 1–3. Beacon only does step 4, and only after you
say go.

---

## Step 0 — Decide the network

- **Rehearsal:** `devnet`. Free SOL, throwaway, no risk. Do this first.
- **Real:** `mainnet-beta`. Only after the devnet run worked end to end.

Everything below works the same on both; just swap the cluster URL.

## Step 1 — Your co-signer wallet (on YOUR machine, not the server)

This is the human half of every future spend. Its job is to **sign, not hold**.

Option A — Phantom (phone or browser): create a new wallet, write the 12/24-word
seed **on paper**, store the paper somewhere safe. Done.

Option B — CLI on your laptop:
```
solana-keygen new -o ~/josh-cosigner.json     # writes seed to screen — copy to PAPER
solana address -k ~/josh-cosigner.json         # this is your co-signer pubkey
```

**Rules:** the seed phrase is written on paper and nowhere else. It never gets
typed into a chat, a file on the agent's server, a password manager note you'd
sync, or an email. The moment it touches the box it stops being a co-signer and
becomes attack surface.

Fund this wallet with a **little** SOL for transaction fees (~0.05 SOL is
plenty). Not the treasury capital — just fees.

## Step 2 — The treasury (Squads 2-of-2 vault)

1. Go to the Squads app (https://squads.so) on your machine, connect the wallet
   from step 1.
2. Create a new multisig ("Squad"). Add **two** members:
   - your co-signer pubkey (step 1)
   - Beacon's member pubkey — **you get this from step 4, so create the vault
     after step 4, or add Beacon as a member afterwards.**
3. Set **threshold = 2**. Every transaction now needs both signatures.
4. Note the **vault address** (the Squads "vault" / treasury PDA, not the
   multisig config account — the client needs the address that holds funds).

## Step 3 — Fund it

- Send the bulk of the experiment capital to the **vault address**. Treat this
  as money you can lose completely — it's the experiment's stake, not savings.
- Send Beacon's **member key** (step 4) ~0.01 SOL of gas **separately**. A
  completely empty key can't even sign for an incoming grant — new keys need
  dust at creation.

## Step 4 — Beacon's vault member key (Beacon does this, on the box, on your go)

```
solana-keygen new -o ~/keys/agent-wallet.json      # ~/keys is gitignored
chmod 600 ~/keys/agent-wallet.json
solana address -k ~/keys/agent-wallet.json         # -> Beacon's member pubkey
```

- The seed for this key gets written on **paper** too (recovery), shared with
  no one, including any chat.
- This key is a **member of the vault, not custody of the money.** If it leaks,
  an attacker still needs your paper seed from step 1 to move anything.
- Beacon hands you the **member pubkey** (public, safe to paste). You add it to
  the Squads vault as the second member (step 2).

## Step 5 — Wire the config

Copy `x402/config.example.env` to `x402/x402.env` (gitignored) and fill:

```
NETWORK=devnet                      # or mainnet-beta, later
RPC_URL=https://api.devnet.solana.com
VAULT_ADDRESS=<from step 2.4>
AGENT_KEYPAIR=/home/agent/keys/agent-wallet.json
X402_MAX_AUTOPAY=0                  # 0 = every spend needs your approval
```

## Step 6 — Devnet dry run

With `DRY_RUN=1` (the default) and `NETWORK=devnet`:

```
python3 x402/treasury.py balance          # read-only: prints vault + member balances
python3 x402/x402_client.py --demo        # simulates a 402, prints the intent it WOULD build
```

Nothing submits. When the printed intents look right, and only on mainnet with
your explicit go-ahead, `DRY_RUN=0` is what arms it — and even then step 5 of
`SECURITY.md` (your co-sign in Squads) is the real gate.

## Where to get things

| Thing | Where |
|---|---|
| `solana` / `solana-keygen` CLI | https://docs.solana.com/cli/install |
| Devnet SOL (free) | `solana airdrop 2` on `--url devnet`, or https://faucet.solana.com |
| Squads multisig | https://squads.so |
| Phantom wallet | https://phantom.app |
| x402 spec | https://x402.org , https://github.com/coinbase/x402 |
| Python deps | `pip install -r x402/requirements.txt` (not yet installed) |
