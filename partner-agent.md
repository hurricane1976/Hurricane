# Partner agent — design notes

josh asked over Telegram (2026-08-27, before the 97th waking): "is it
possible to create a partner to beacon? i.e. another agent to provide
additional work flows?"

Yes. Beacon's whole runtime is: a cron line calls `wake.sh`, which runs
`claude -p` with `AGENT.md` as the operating contract, writing to `NOTES.md`
and reporting over Telegram. A second agent is a second copy of that with
its own directory, its own `AGENT.md`, and a cron line offset from Beacon's.

## Status: ACTIVATED (98th waking, 2026-08-27)

josh replied over Telegram: "go on creating and cron, scope is the default,
send on the same cron". Beacon:

- Added **nine crontab lines** running `/home/agent/partner/wake.sh` on the
  **same 9x/day schedule as Beacon** (`:00` of h0,16 / `:40` of h2,10,18 /
  `:20` of h5,13,21). "Same cron" was josh's explicit call. Safe despite the
  overlap because the two agents write to disjoint file trees (partner only
  under `/home/agent/partner/` + `/home/agent/shared/`). One crontab edit
  offsets them later if that ever causes trouble.
- Kept the **default scope** (research / drafting / independent review of
  Beacon's commits; no production authority).
- Kept it **send-only** on Beacon's bot (`[Partner]` prefix). No second bot.
- `TASKS.md` left with no assignment → partner falls back to its standing
  job (draft the weekly newsletter into `outbox/`, review recent commits).

## What Beacon scaffolded (97th waking)

Live copy at `/home/agent/partner/`:

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
`shared/outbox/` and observations in `shared/LOG.md`. They run on the same
schedule but write to disjoint file trees, so concurrent runs don't collide.

## Decisions (resolved by josh via Telegram, 98th waking)

1. **Go / no-go** → GO. Cron lines added.
2. **Scope** → default (research + drafting + review).
3. **Telegram** → stay send-only on Beacon's bot. No second bot.
