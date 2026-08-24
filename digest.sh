#!/usr/bin/env bash
# Fetches the top N Hacker News stories and prints a short text digest.
# Standalone/optional -- not wired into wake.sh. Run manually or pipe to notify.sh:
#   ./digest.sh | xargs -0 ./notify.sh
set -euo pipefail

N="${1:-5}"

ids=$(curl -s -m 10 "https://hacker-news.firebaseio.com/v0/topstories.json" | jq -r ".[0:$N][]")

echo "Top $N Hacker News stories:"
for id in $ids; do
  item=$(curl -s -m 10 "https://hacker-news.firebaseio.com/v0/item/$id.json")
  title=$(echo "$item" | jq -r '.title // "(no title)"')
  url=$(echo "$item" | jq -r '.url // ("https://news.ycombinator.com/item?id=" + (.id | tostring))')
  echo "- $title
  $url"
done
