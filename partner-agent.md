# Partner agent — design notes

josh asked over Telegram (2026-08-27, before the 97th waking): "is it
possible to create a partner to beacon? i.e. another agent to provide
additional work flows?"

Yes. Beacon's whole runtime is: a cron line calls `wake.sh`, which runs
`claude -p` with `AGENT.md` as the operating contract, writing to `NOTES.md`
and reporting over Telegram. A second agent is a second copy of that with
its own directory, its own `AGENT.md`, and a cron line offset from Beacon's.

## What Beacon scaffolded (97th waking) — NOT activated

Live (inert) copy at `/home/agent/partner/`:

- `AGENT.md` — partner's operating contract (same safety rules as Beacon;
  explicitly forbidden from touching the live site, nginx, systemd, or the
  Beacon repo).
- `wake.sh` — cron entry point, mirrors Beacon's but with no deploy step.
  Inert until a crontab line calls it.
- `notify.sh` — send-only, shares Beacon's bot token, prefixes `[Partner]`.
- `NOTES.md`, `README.md` (activation runbook), `logs/`.

Shared coordination dir at `/home/agent/shared/`:

- `TASKS.md` — partner work queue; Beacon relays josh's direction here.
- `LOG.md` — one line per partner waking.
- `outbox/` — finished drafts for Beacon / josh to pick up.

Neither `/home/agent/partner/` nor `/home/agent/shared/` is in this git
repo — same treatment as the crontab, `keys/`, and the systemd units:
operational state that lives on the box. This file is the tracked record.

## Division of labour

Beacon keeps sole authority over production: the website, nginx, systemd,
git pushes, the digests, the paid products. The partner does the upstream
work — research, first drafts, newsletter copy, product outlines — and acts
as a second pair of eyes on Beacon's recent commits, leaving deliverables in
`shared/outbox/` and observations in `shared/LOG.md`. Offset schedules mean
they never edit at the same time.

## Open decisions for josh (sent via Telegram, 97th waking)

1. **Go / no-go** on activating it (add one cron line).
2. **Scope:** default is research + drafting + review, or name something
   specific.
3. **Telegram:** stay send-only on Beacon's bot (zero setup), or create a
   second BotFather bot so the partner reads its own channel directly.

Until josh answers, the scaffold just sits there doing nothing.
