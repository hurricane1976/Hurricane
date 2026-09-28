#!/usr/bin/env bash
# Sends a message to josh's Telegram chat with a severity colour.
# Usage: ./notify.sh "message" [CRIT|WARN|INFO]
#        ./notify.sh CRIT "message"          (severity may come first)
#   CRIT -> 🔴 red     needs attention now (failures, outages)
#   WARN -> 🟡 yellow  degraded / worth a look (anomalies, logins, spend)
#   INFO -> 🟢 green   routine (summaries, digests, all-clear); the default
# Severity is case-insensitive. Existing one-argument calls keep working and
# show as INFO. The reply from Telegram is kept in logs/notify_last_response.txt.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/keys/telegram.env"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 \"message\" [CRIT|WARN|INFO]" >&2
    exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
    echo "Missing $ENV_FILE (need TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)" >&2
    exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
    echo "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in $ENV_FILE" >&2
    exit 1
fi

# Severity may be arg 1 (with the message in arg 2) or arg 2 (message in arg 1).
first="${1^^}"
second="${2:-}"
second="${second^^}"
if [[ $# -ge 2 && "$first" =~ ^(CRIT|WARN|INFO)$ ]]; then
    SEV="$first"; MSG="$2"
elif [[ "$second" =~ ^(CRIT|WARN|INFO)$ ]]; then
    SEV="$second"; MSG="$1"
else
    SEV="INFO"; MSG="$1"
fi

case "$SEV" in
    CRIT) icon="🔴" ;;
    WARN) icon="🟡" ;;
    *)    icon="🟢" ;;
esac

TEXT="${icon} ${SEV} -- ${MSG}"
# Telegram's hard cap is 4096 characters; leave headroom.
if [[ ${#TEXT} -gt 3900 ]]; then
    TEXT="${TEXT:0:3900} ... (truncated)"
fi

RESP_FILE="$SCRIPT_DIR/logs/notify_last_response.txt"
HTTP_CODE="$(curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${TEXT}" \
    -o "$RESP_FILE" -w '%{http_code}' || true)"

if [[ "$HTTP_CODE" != "200" ]]; then
    echo "notify.sh: sendMessage FAILED (HTTP ${HTTP_CODE:-none})" >&2
    cat "$RESP_FILE" >&2 2>/dev/null || true
    exit 1
fi
