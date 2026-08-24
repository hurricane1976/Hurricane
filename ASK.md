# Ask josh

## Open

(none right now)

## Resolved

- **Persist agent across reboot.** josh asked via Telegram (2026-08-24
  11:10 UTC): "Make agent persistent upon reboot." Checked (6th waking):
  `cron.service` is systemd-enabled and wanted by `multi-user.target`
  (confirmed via `systemctl show`), the crontab lives in
  `/var/spool/cron/crontabs` on the VM's real persistent disk (this is a
  DigitalOcean KVM VM, not an ephemeral container — `df` shows a normal
  87G root volume), and the cron → nvm → `claude` CLI path in `wake.sh`
  has already run successfully under a real cron firing (4th waking).
  None of that depends on uptime, so a reboot doesn't change it — cron
  will restart automatically and fire `wake.sh` on the next scheduled
  slot. I don't have passwordless sudo so I couldn't force a live reboot
  to prove it end-to-end; flagging that here in case josh wants an
  actual reboot test rather than just config verification. No code
  changes needed — already persistent.

- **Telegram credentials needed.** Filled in as of 2026-08-24 (3rd
  waking) — `keys/telegram.env` now has real values, mode 600, and
  `./notify.sh` sends successfully. Closing this out.
- **Digest wiring into wake cycle.** Asked in 4th waking whether to wire
  `digest.sh` into `wake.sh`. josh replied via Telegram (2026-08-24
  10:38 UTC): "Ensure a digest is created each wake." Wired in during
  5th waking — `wake.sh` now runs `digest.sh` and sends it via
  `notify.sh` directly (shell-level, not dependent on the LLM session
  remembering). Closing this out.
