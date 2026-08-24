#!/usr/bin/env bash
# Prints a short text digest: top Hacker News stories, plus global (BBC) and
# US (NPR) news headlines. Wired into wake.sh -- runs at every scheduled wake.
#
# Each section fetches from an external source and is allowed to fail
# independently -- a transient network hiccup on one source (or one HN item)
# prints a "(unable to fetch ...)" note for that piece instead of aborting
# the whole digest, since this runs unattended 3x/day with nobody to notice
# a silent empty run.
set -uo pipefail

N="${1:-5}"

echo "Top $N Hacker News stories:"
ids=$(curl -s -m 10 "https://hacker-news.firebaseio.com/v0/topstories.json" | jq -r ".[0:$N][]" 2>/dev/null)
if [ -z "$ids" ]; then
  echo "(unable to fetch Hacker News)"
else
  for id in $ids; do
    item=$(curl -s -m 10 "https://hacker-news.firebaseio.com/v0/item/$id.json")
    if [ -z "$item" ]; then
      continue
    fi
    title=$(echo "$item" | jq -r '.title // "(no title)"' 2>/dev/null)
    url=$(echo "$item" | jq -r '.url // ("https://news.ycombinator.com/item?id=" + (.id | tostring))' 2>/dev/null)
    [ -n "$title" ] && echo "- $title
  $url"
  done
fi

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

echo
echo "Global news (BBC World):"
rss_headlines "https://feeds.bbci.co.uk/news/world/rss.xml" "$N"

echo
echo "US news (NPR):"
rss_headlines "https://feeds.npr.org/1001/rss.xml" "$N"

exit 0
