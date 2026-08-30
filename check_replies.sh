#!/usr/bin/env bash
# Prints any new Telegram messages from josh since the last check, and
# advances the saved offset so they aren't shown again next time.
# Usage: ./check_replies.sh
#
# Two sources, in order:
#   1. .telegram_incoming -- non-command messages queued by the between-wakings
#      command poller (telegram_commands.py), which is the primary consumer of
#      the update stream. Drained and cleared here.
#   2. a direct getUpdates poll -- unchanged fallback. Normally returns nothing
#      because the poller already advanced the shared offset, but keeps this
#      script fully functional on its own if the poller is stopped.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/keys/telegram.env"
OFFSET_FILE="$SCRIPT_DIR/.telegram_offset"
INCOMING_FILE="$SCRIPT_DIR/.telegram_incoming"

if [[ -s "$INCOMING_FILE" ]]; then
    echo "-- queued by the command poller since the last check --"
    cat "$INCOMING_FILE"
    rm -f "$INCOMING_FILE"
    echo "-- end queued --"
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

LAST_OFFSET=0
if [[ -f "$OFFSET_FILE" ]]; then
    LAST_OFFSET="$(cat "$OFFSET_FILE")"
fi

RESP="$(curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates?offset=$((LAST_OFFSET + 1))")"

# Print only messages genuinely from josh's configured chat id, and
# persist the highest update_id seen so they aren't shown again.
echo "$RESP" | python3 "$SCRIPT_DIR/_check_replies.py" "$TELEGRAM_CHAT_ID" "$OFFSET_FILE"
