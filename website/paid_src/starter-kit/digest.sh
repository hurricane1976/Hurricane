#!/usr/bin/env bash
# Prints a short text digest: world news headlines plus a local weather
# forecast. Meant to be piped into notify.sh, either every wake or gated
# to once a day (see daily_digest.sh.example below).
set -uo pipefail

N="${1:-5}"

weather_forecast() {
  # Replace GRIDPOINT_URL below with your own NWS gridpoint forecast URL.
  # To find it: look up your location's lat/lon (e.g. via a geocoder),
  # then GET https://api.weather.gov/points/{lat},{lon} -- the response's
  # properties.forecast field is the URL you want. It's static for a fixed
  # location, so resolve it once and hardcode it here (skips a lookup call
  # on every digest). No API key needed; NWS asks for a contact email in
  # the User-Agent string as a courtesy.
  local gridpoint_url="https://api.weather.gov/gridpoints/GRIDPOINT_URL/forecast"
  local out
  out=$(curl -s -m 10 -A "MyAgent/1.0 (contact: YOUR_EMAIL)" \
    "$gridpoint_url" | python3 -c "
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
echo "Weather:"
weather_forecast

# Each section degrades independently (prints a fetch-failed placeholder
# instead of aborting) and the script always exits 0 -- a transient outage
# in one feed shouldn't cost you the whole digest, and a hard failure here
# shouldn't block whatever calls this and pipes the output to notify.sh.
exit 0
