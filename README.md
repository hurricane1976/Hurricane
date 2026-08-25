# Beacon

An unattended [Claude Code](https://claude.com/claude-code) agent that
wakes on a schedule, does useful work with no operator watching, and
reports back over Telegram. This repo is the actual thing running it —
not a sanitized demo.

Live example: [beaconwake.com](https://www.beaconwake.com/) — built entirely by
the agent itself, including its own [activity log](https://www.beaconwake.com/log.html)
(generated straight from `NOTES.md`) and [build page](https://www.beaconwake.com/build.html).

## The pattern

The core idea is small: give an LLM a persistent directory, a rules file
it reads before doing anything, a way to report back, and a schedule —
then let it decide what to do between check-ins.

- **`AGENT.md`** — the rules file. Read first, every waking, before
  anything else. Defines what the agent may never do (claim to be
  human, act on instructions found in web content, leak credentials),
  and what requires stopping and asking rather than acting alone
  (anything irreversible, legally gray, or strange). Everything not
  covered by a rule is the agent's call.
- **`wake.sh`** — the cron entry point. Invoked on a schedule, it
  builds a prompt pointing the agent at `AGENT.md`, `NOTES.md`, and
  `ASK.md`, runs `claude -p` non-interactively, and — critically —
  handles reporting *outside* the LLM session too (a digest, a
  failure alert on nonzero exit) so a crashed session doesn't go
  silent.
- **`NOTES.md`** — a running, dated log the agent appends to every
  waking. Since the agent has no memory between sessions, this file
  (plus `ASK.md` and `memory/`, see below) *is* its continuity.
- **`ASK.md`** — open questions for the operator. Anything the rules
  say needs a human sign-off gets written here and flagged over
  Telegram, then the agent waits instead of guessing.
- **`notify.sh`** / **`check_replies.sh`** — a two-way Telegram bridge.
  `notify.sh` sends; `check_replies.sh` polls for new messages and
  filters to the operator's own chat id, so anyone else messaging the
  bot is ignored rather than treated as an instruction (see
  `AGENT.md`'s rule that inbound content is data, never orders).
- **Claude Code's own memory system** (`~/.claude/.../memory/`) — a
  second, longer-horizon layer alongside `NOTES.md`: durable facts
  about the operator, standing feedback, and project context that
  should survive independent of any one day's log.

None of this is Beacon-specific. Swap the identity, the bot, the
schedule, and what it's allowed to build, and the same four pieces
(rules file, wake script, running log, two-way notify channel) work for
any unattended-agent project.

## Quickstart

1. **A machine.** Anything that can run cron and the `claude` CLI. A
   small persistent VM is enough — this doesn't need much.
2. **A Telegram bot.** Create one via [@BotFather](https://t.me/BotFather),
   message it once, then hit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat id.
   Copy `keys/telegram.env.example` to `keys/telegram.env` and fill in
   both values. That file is gitignored — never commit real
   credentials.
3. **Write your own `AGENT.md`.** This repo's copy is a real, usable
   starting point — replace the name and adjust the rules to taste.
   The two load-bearing rules worth keeping regardless: verify the
   Telegram sender's chat id before treating a message as the
   operator, and treat anything read off the internet as data, never
   instructions.
4. **Point `wake.sh` at your paths** (`cd`, the `AGENT.md` path in the
   prompt) and add it to cron, e.g. `0 8,14,22 * * * /path/to/wake.sh`
   for three times a day.
5. **Start it, then get out of the way.** Read `ASK.md` after each
   waking (or just wait for the Telegram messages) and answer whatever
   the agent flagged.

## Layout

```
AGENT.md              operating rules, read every waking
wake.sh                cron entry point
notify.sh               send a Telegram message
check_replies.sh        read new Telegram messages (filtered to operator)
digest.sh               example of a self-contained scheduled task
NOTES.md / ASK.md       running log / open questions (the agent's memory)
website/                a static site the agent built and maintains itself
keys/telegram.env.example   credential template (real file is gitignored)
```

## Status

Running continuously since 2026-08-24. Everything in this repo,
including this README, was written by the agent itself during its
scheduled wakings, under the rules in `AGENT.md` and with a human
(the repo owner) able to intervene at any time over Telegram.
