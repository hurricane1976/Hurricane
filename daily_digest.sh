#!/usr/bin/env bash
# Sends the digest once per day at 0800 Eastern, regardless of DST.
# Run hourly via cron; self-gates on local Eastern hour + a state file so
# it only actually sends once per calendar day even if cron fires more
# than once in the 8 o'clock hour.
#
# josh asked (2026-08-25) to stop sending a digest every wake (was 15x/day)
# and instead send just one, in the morning, at 0800 EST. Implemented as
# an hourly local-time check against America/New_York rather than a fixed
# UTC cron time so it doesn't drift off 8am wall-clock time across the
# March/November DST changes.
set -uo pipefail
cd /home/agent/agent || exit 1

STATE_FILE=".digest_sent_date"
TODAY_ET="$(TZ=America/New_York date +%F)"
HOUR_ET="$(TZ=America/New_York date +%H)"

[ "$HOUR_ET" = "08" ] || exit 0
[ -f "$STATE_FILE" ] && [ "$(cat "$STATE_FILE")" = "$TODAY_ET" ] && exit 0

if DIGEST="$(./digest.sh 5 2>>logs/daily_digest.log)"; then
    ./notify.sh "$DIGEST" >>logs/daily_digest.log 2>&1 && echo "$TODAY_ET" >"$STATE_FILE"
else
    echo "$(date -u +%FT%TZ) digest.sh failed" >>logs/daily_digest.log
fi
