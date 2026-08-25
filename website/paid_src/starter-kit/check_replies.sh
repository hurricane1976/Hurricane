#!/usr/bin/env bash
# Prints any new Telegram messages from you since the last check, and
# advances the saved offset so they aren't shown again next time.
# Usage: ./check_replies.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/keys/telegram.env"
OFFSET_FILE="$SCRIPT_DIR/.telegram_offset"

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

LAST_OFFSET=0
if [[ -f "$OFFSET_FILE" ]]; then
    LAST_OFFSET="$(cat "$OFFSET_FILE")"
fi

RESP="$(curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates?offset=$((LAST_OFFSET + 1))")"

# Print only messages genuinely from your configured chat id, and persist
# the highest update_id seen so they aren't shown again.
echo "$RESP" | python3 "$SCRIPT_DIR/_check_replies.py" "$TELEGRAM_CHAT_ID" "$OFFSET_FILE"
