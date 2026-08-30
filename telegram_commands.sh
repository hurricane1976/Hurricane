#!/usr/bin/env bash
# Cron wrapper for telegram_commands.py -- the dynamic Telegram command
# handler. Runs every few minutes; flock-guarded so a slow run (e.g. one
# that shelled out to /digest) can't overlap the next tick and double-read
# the update stream.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p logs

ENV_FILE="$SCRIPT_DIR/keys/telegram.env"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "$(date -u +%FT%TZ) missing $ENV_FILE" >&2
    exit 1
fi

exec 9>"logs/.telegram_commands.lock"
if ! flock -n 9; then
    exit 0
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

exec python3 "$SCRIPT_DIR/telegram_commands.py"
