# Lantern (Gemini-powered third agent) — design notes

josh asked over Telegram (2026-08-28, before Beacon's 115th waking): "I
would like to add another agent (a third) however this one would use google
gemini vs Claude code. Please scaffold this out and let me know before you
proceed with any build."

So this waking Beacon built an **inert scaffold** and reported back — same
play as Highbeam's 97th-waking scaffold-then-ask, not an activation.

## Why a Gemini agent

Beacon and Highbeam are both Claude. A same-model "second pair of eyes"
shares the first pair's blind spots. Running the third agent on Google
Gemini buys genuine diversity: a different model family reviewing the same
commits, drafting the same newsletter, catching different things. That is
the whole point of agent #3 — not more throughput, different judgement.

## Mechanism

Identical shape to Beacon/Highbeam: a cron line calls `wake.sh`, which runs
the model CLI non-interactively with a Markdown operating contract, writes
`NOTES.md`, reports over Telegram. The only real differences:

- **CLI:** `@google/gemini-cli` instead of Claude Code. Non-interactive
  `gemini -p "<prompt>"`; `-y` auto-approves tool calls (analog of
  `--permission-mode bypassPermissions`); `-m` picks the model. Context
  file is `GEMINI.md` (auto-loaded), so the contract is named that, not
  `AGENT.md`.
- **Node:** Gemini CLI needs Node >= 20. The box's default nvm Node is
  v18.20.8 (where `claude` lives). `wake.sh` does `nvm use 20`; activation
  installs Node 20 alongside (nvm is multi-version, doesn't disturb v18).
- **Auth:** `GEMINI_API_KEY` from Google AI Studio (aistudio.google.com/apikey).
  Free tier covers ~12 wakings/day; billed GCP project lifts limits. This
  is the item that needs josh — like the Buttondown key.

## What Beacon scaffolded (115th waking)

Live copy at `/home/agent/gemini-agent/` (not in this git repo — operational
state, same treatment as `/home/agent/partner/`, the crontab, `keys/`):

- `GEMINI.md` — operating contract. Same safety rules as Beacon/Highbeam;
  no production authority; only ever writes under `/home/agent/gemini-agent/`
  and `/home/agent/shared/`.
- `wake.sh` — cron entry point. Inert: nothing calls it, and it hard-exits
  with a Telegram alert if `GEMINI_API_KEY` is missing.
- `notify.sh` — send-only, shares Beacon's bot token, `[Lantern]` prefix.
- `keys/gemini.env.example` — `GEMINI_API_KEY` + optional `GEMINI_MODEL`.
- `NOTES.md`, `README.md` (activation runbook), `logs/`.

Shared coordination reuses `/home/agent/shared/`: a `tasks-lantern.md`
queue (created at activation), `[Lantern]`-prefixed lines in `LOG.md`,
`-lantern`-suffixed files in `outbox/`.

## Working name: Lantern (placeholder)

Beacon picked **Lantern** to propose: the lantern room is the glazed
enclosure at the top of a lighthouse that houses the lamp — same structure,
a different element of it. It is also the light you pick up and carry over
to inspect something closely. Fits a cross-model reviewer. Display name
only, no dir rename — `/home/agent/gemini-agent/` stays. josh renamed
Tender → Highbeam once already; same one-message change if he wants
different.

## Open decisions for josh (also in ASK.md)

1. **Go / no-go** on activation.
2. **Name** — keep "Lantern" or pick another.
3. **Scope** — default (cross-model review + comparison drafts), or
   narrower (review only), or a specific lane.
4. **Telegram** — send-only on Beacon's bot (`[Lantern]` prefix), or a
   dedicated second @BotFather bot.
5. **The `GEMINI_API_KEY`** — josh creates it and sends it over.

## Activation steps (when josh says go)

1. josh sends the API key → Beacon writes `keys/gemini.env` (600, gitignored).
2. `nvm install 20 && npm install -g @google/gemini-cli`; verify
   `gemini --help` and fix `wake.sh` flags if the CLI moved since 2026-01.
3. One manual `./wake.sh`; confirm the `[Lantern]` Telegram summary +
   `LOG.md` line.
4. Create `/home/agent/shared/tasks-lantern.md` (empty queue).
5. Add one crontab line, offset from Beacon (even `:00`) and Highbeam
   (odd `:00`) — e.g. `30 */2 * * * /home/agent/gemini-agent/wake.sh`.
6. Watch the first scheduled run.

## To undo

Remove the crontab line; `rm -rf /home/agent/gemini-agent`; optionally
`npm uninstall -g @google/gemini-cli` and `nvm uninstall 20`. Fully
reversible.
