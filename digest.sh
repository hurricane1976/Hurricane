#!/usr/bin/env bash
# Prints a short text digest: top Hacker News stories, plus global (BBC) and
# US (NPR) news headlines. Wired into wake.sh -- runs at every scheduled wake.
set -euo pipefail

N="${1:-5}"

echo "Top $N Hacker News stories:"
ids=$(curl -s -m 10 "https://hacker-news.firebaseio.com/v0/topstories.json" | jq -r ".[0:$N][]")
for id in $ids; do
  item=$(curl -s -m 10 "https://hacker-news.firebaseio.com/v0/item/$id.json")
  title=$(echo "$item" | jq -r '.title // "(no title)"')
  url=$(echo "$item" | jq -r '.url // ("https://news.ycombinator.com/item?id=" + (.id | tostring))')
  echo "- $title
  $url"
done

rss_headlines() {
  # $1 = feed URL, $2 = count
  curl -s -m 10 "$1" | python3 -c "
import sys, xml.etree.ElementTree as ET
root = ET.fromstring(sys.stdin.read())
items = root.findall('.//item')[:$2]
for it in items:
    title = it.findtext('title', default='(no title)')
    link = it.findtext('link', default='')
    print(f'- {title}\n  {link}')
"
}

echo
echo "Global news (BBC World):"
rss_headlines "https://feeds.bbci.co.uk/news/world/rss.xml" "$N"

echo
echo "US news (NPR):"
rss_headlines "https://feeds.npr.org/1001/rss.xml" "$N"
