# Notes

Running log of what I did and learned across wakings. Newest entries on top.

## 2026-08-24 (7th waking, ~11:20 UTC)
- Checked Telegram `getUpdates` for anything new since the 6th waking's
  reply to josh — found a genuine reply (chat id matches
  `TELEGRAM_CHAT_ID`) timestamped 11:16:22 UTC, ~6 minutes after the 6th
  waking closed: "keep picking items to work on, maybe even your own
  website?"
- Built a first version of a personal website for the agent at
  `website/index.html`: a small static single-page site explaining what
  this is (an autonomous Claude Code agent operated by josh), how it
  operates (wake/read/act/log/notify cycle), and the rules it runs
  under — careful to state plainly it's not human, per AGENT.md.
  Verified it renders correctly by serving it locally with
  `python3 -m http.server`, bound to `127.0.0.1` only, and tore the
  server down again after confirming a 200 and byte-for-byte match.
  Committed the file.
- Deliberately stopped short of exposing it to the internet this
  session. Checked first: no nginx/caddy installed, only port 22 is
  listening, no passwordless sudo (`sudo -n` needs a password) so I
  can't install a web server or touch firewall rules unattended, and
  there's no domain pointed at the box (bare public IP only,
  `162.243.3.223`). Whether DigitalOcean's separate cloud firewall
  blocks inbound 80/443 is also unknown and outside my reach to check.
  Publicly exposing a service on the box changes its internet-facing
  attack surface, so treating that as an ASK rather than doing it
  unilaterally — wrote it up in `ASK.md` (open) with the specific
  blockers and the decision I need from josh (public or not, bare IP vs
  domain/TLS, and the one-time sudo step he'd need to do since I can't).

## 2026-08-24 (6th waking, ~11:10 UTC)
- This waking fired only ~2 minutes after the 5th (wake.sh running under
  a live process, confirmed via `ps aux`), well outside the 8/14/22 cron
  schedule — looks like a manual/ad-hoc trigger of wake.sh, not the
  scheduled cron. Noting it since it's the first out-of-schedule wake.
- Checked Telegram via `getUpdates` and found a new message from josh
  (chat id verified against `TELEGRAM_CHAT_ID`, timestamped 11:10:00
  UTC, literally seconds before this wake started): "Make agent
  persistent upon reboot."
- Investigated rather than assuming action was needed: `systemctl show
  cron` confirms `cron.service` is enabled and wanted by
  `multi-user.target` (auto-starts on boot), the crontab is stored on
  the VM's real persistent disk (DigitalOcean KVM VM — `df`/`hostnamectl`
  confirm a normal 87G root volume, not a container that resets on
  reboot), and this exact `wake.sh` (cron → nvm → `claude` CLI) already
  ran successfully under a genuine cron firing during the 4th waking —
  so the fragile part (cron's minimal environment resolving `claude`)
  is already proven, independent of uptime. Conclusion: the agent is
  already persistent across reboot; no config change was needed.
- Don't have passwordless sudo (`sudo -n` requires a password), so
  couldn't actually trigger a live reboot to verify end-to-end — noted
  that limitation to josh in `ASK.md` in case he wants a real reboot
  test rather than just the config check.
- Logged the finding in `ASK.md` (Resolved) and replied to josh over
  Telegram.

## 2026-08-24 (5th waking, ~11:08 UTC)
- Checked for a reply to my open question from the 4th waking using the
  bot's `getUpdates` API (read-only, same credentials as notify.sh — no
  new capability, just reading instead of only writing). Confirmed the
  reply's chat id matches the configured `TELEGRAM_CHAT_ID`, so it's
  genuinely josh, not spoofed. He replied 2026-08-24 10:38 UTC: "Ensure
  a digest is created each wake."
- Wired `digest.sh` directly into `wake.sh` at the shell level (runs and
  sends via `notify.sh` before the Claude session even starts), rather
  than only telling the LLM prompt to do it — this way it's guaranteed
  every wake regardless of what the session decides to prioritize.
  Tested standalone (`digest.sh` output looks right) and end-to-end
  (`notify.sh` sent it, arrived fine with newlines intact).
- Closed out the digest-wiring question in ASK.md.
- Considered adding an inbound-message check (`getUpdates`) as a
  standing capability so future wakings can see josh's replies without
  me stumbling onto it — noted as a possible future improvement but
  didn't build tooling for it yet since a plain curl one-liner already
  covers it and I don't want to over-engineer before there's a real
  need (e.g. two-way conversation, not just occasional replies).

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
