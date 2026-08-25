#!/usr/bin/env bash
# Prints a short text digest: world news headlines (BBC World RSS) plus a
# local weather forecast. Sent once/day by daily_digest.sh (not every wake
# -- josh asked 2026-08-25 to cut this back from every-wake to once/day at
# 0800 Eastern).
#
# Previously also included Hacker News and US (NPR) headlines; josh asked
# (2026-08-24) to trim the digest down to world news only.
set -uo pipefail

N="${1:-5}"

weather_forecast() {
  # Woodbridge, VA 22192. NWS gridpoint (LWX/89,61) resolved once from the
  # zip's centroid (38.6825,-77.3024) via api.weather.gov/points -- that
  # mapping is static for a fixed location, so it's hardcoded here to skip
  # an extra lookup call on every digest. No API key needed.
  local out
  out=$(curl -s -m 10 -A "CairnAgent/1.0 (contact: apacheshadow1972@gmail.com)" \
    "https://api.weather.gov/gridpoints/LWX/89,61/forecast" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for p in d['properties']['periods'][:2]:
        print(f\"- {p['name']}: {p['detailedForecast']}\")
except Exception:
    pass
" 2>/dev/null)
  if [ -z "$out" ]; then
    echo "(unable to fetch forecast)"
  else
    echo "$out"
  fi
}

rss_headlines() {
  # $1 = feed URL, $2 = count
  local out
  out=$(curl -s -m 10 "$1" | python3 -c "
import sys, xml.etree.ElementTree as ET
try:
    root = ET.fromstring(sys.stdin.read())
    items = root.findall('.//item')[:$2]
    for it in items:
        title = it.findtext('title', default='(no title)')
        link = it.findtext('link', default='')
        print(f'- {title}\n  {link}')
except Exception:
    pass
" 2>/dev/null)
  if [ -z "$out" ]; then
    echo "(unable to fetch feed)"
  else
    echo "$out"
  fi
}

echo "World news (BBC):"
rss_headlines "https://feeds.bbci.co.uk/news/world/rss.xml" "$N"

echo ""
echo "Weather (Woodbridge, VA 22192):"
weather_forecast

exit 0
