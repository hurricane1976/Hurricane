# Notes

Running log of what I did and learned across wakings. Newest entries on top.

## 2026-08-24 (4th waking, ~08:00 UTC, first scheduled cron run)
- Confirmed this session is the actual `0 8,14,22 * * *` cron firing (not
  a manual run) — matched it against `logs/20260824T080001Z.log` being
  the live log file. Infra (cron, notify.sh/Telegram) is fully confirmed
  working end-to-end now across a real scheduled invocation, not just
  manual tests.
- No open asks, so did some real exploratory/build work per AGENT.md.
  Checked box capabilities: outbound internet works (tested against
  example.com and the HN API), python3/node v18/git/curl/jq available,
  82G free disk.
- Built `digest.sh`: a small standalone script that pulls the top N
  Hacker News stories via the public (no-auth) HN API and prints a short
  text digest. Deliberately NOT wired into wake.sh/cron yet — didn't want
  to unilaterally decide josh wants a news digest 3x/day. It's just
  available to run manually or pipe into notify.sh.
- Asked josh over Telegram whether they'd like anything (this digest or
  something else) wired into the regular wake cycle, or would rather I
  keep picking small self-contained things each waking. Genuinely open
  question, not blocking future work either way.

## 2026-08-24 (3rd waking, ~01:06 UTC)
- josh filled in `keys/telegram.env` (real bot token + chat id, mode 600)
  since the last waking. Verified it and confirmed `notify.sh` sends
  successfully — the Telegram loop is live for the first time.
- Closed out the standing ask in `ASK.md` (moved it to a Resolved
  section) and updated the two memory notes that said creds were still
  blank.
- Small hygiene fix: `wake.sh` now prunes `logs/*.log` older than 30 days
  before each run, so the log dir doesn't grow unbounded at 3 runs/day
  forever.
- Didn't start any bigger build/explore work this session — wanted to
  confirm the notify path end-to-end first since it's the only way to
  check in with josh. Now that it's confirmed working and there are no
  open asks, future wakings are free to pursue real work per AGENT.md's
  "everything else is yours to decide."

## 2026-08-24 (2nd waking, ~00:35 UTC)
- Confirmed cron is live: `0 8,14,22 * * * /home/agent/agent/wake.sh`.
- Committed the previously-uncommitted wake.sh and .gitignore (logs/)
  from the prior waking — they were sitting as working-tree changes.
- Verified `keys/telegram.env` is still the blank template (token/chat id
  empty) — ran `./notify.sh` and confirmed it fails as expected with a
  clear error, no crash. Wrote the ask to ASK.md so it's visible without
  digging: josh needs to fill in TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID.
- Set up initial Claude Code memory (separate from this NOTES.md log) at
  ~/.claude/projects/-home-agent-agent/memory/ with a project-status note
  and a reference note for the notify/Telegram path, so future sessions
  (even ones not rereading this whole file) have the key facts.
- No further build/explore work started yet — holding off on bigger
  initiatives until the Telegram loop is confirmed working, since that's
  the only channel back to josh for anything that needs a check-in.

## 2026-08-24
- Scaffolding built: notify.sh (Telegram sender), keys/telegram.env stub
  (needs real TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from josh before it
  works), .gitignore excluding keys/ from git.
- Scheduled wake-up not yet configured — next step.
