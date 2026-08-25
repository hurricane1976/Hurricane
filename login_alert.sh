#!/usr/bin/env bash
# Notifies josh via Telegram of any new successful SSH login since last
# check. Meant to run on a tight cron interval (independent of wake.sh's
# 5x/day LLM sessions) so a login gets flagged promptly, not hours later.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

STATE_FILE="$SCRIPT_DIR/.login_alert_since"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
SINCE="$(cat "$STATE_FILE" 2>/dev/null || date -u -d '-15 minutes' +%Y-%m-%dT%H:%M:%SZ)"

NEW_LOGINS="$(sudo -n journalctl -u ssh --since "$SINCE" -o cat 2>/dev/null \
    | grep -E "Accepted (publickey|password) for" || true)"

echo "$NOW" > "$STATE_FILE"

if [[ -n "$NEW_LOGINS" ]]; then
    ./notify.sh "SSH login(s) since $SINCE:
$NEW_LOGINS"
fi
