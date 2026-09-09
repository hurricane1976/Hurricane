#!/usr/bin/env bash
# Non-blocking dependency audit for the deploy gate (fleet-security option E1).
#
# Runs `npm audit` against the React front door (website/site) at most once
# per ~20h and Telegrams josh only when the high+critical advisory count rises
# above the last recorded value. Always exits 0 -- it must never block or fail
# a deploy. The Python build scripts are stdlib-only and the nostr venv is a
# handful of pinned packages with no audit tool installed, so this covers the
# real third-party surface (the npm dependency tree).
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"

STAMP=data/.dep-audit-last
STATE=data/dep-audit-state.txt   # single integer: last high+critical count
NOTIFY=../notify.sh

# Throttle: skip if we audited within the last ~20h (1200 min). Keeps routine
# 6x/day deploys fast; the audit only needs to run about daily.
if [ -f "$STAMP" ] && find "$STAMP" -mmin -1200 2>/dev/null | grep -q .; then
    exit 0
fi

command -v npm >/dev/null 2>&1 || exit 0
[ -d site/node_modules ] || exit 0
touch "$STAMP"

COUNT="$( (cd site && npm audit --json 2>/dev/null) | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print(0); sys.exit(0)
v = (d.get("metadata") or {}).get("vulnerabilities") or {}
print(int(v.get("high", 0)) + int(v.get("critical", 0)))
' )"
[ -n "$COUNT" ] || exit 0

PREV="$(cat "$STATE" 2>/dev/null || echo 0)"
echo "$COUNT" > "$STATE"

if [ "$COUNT" -gt "$PREV" ] 2>/dev/null; then
    "$NOTIFY" "dep-audit: npm high/critical advisories in website/site rose ${PREV} -> ${COUNT}. Run 'cd website/site && npm audit' for detail." || true
fi
exit 0
