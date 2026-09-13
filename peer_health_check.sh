#!/usr/bin/env bash
# AGENT.md Rule 7 (Fleet mesh): once per waking, health-check every peer we
# hold a credential for and log the result. Reuses send_to_peer.sh's own
# POST /inbox path (same auth, same on-demand-not-standing connection) rather
# than duplicating its parsing/curl logic -- a health check is just a normal
# authenticated send with a fixed subject.
#
# Maintains a small JSON state file of consecutive misses per peer so a
# waking can tell whether a peer has now missed 3 in a row (AGENT.md's
# escalate-to-josh threshold) without re-reading the whole log.
#
# Usage: ./peer_health_check.sh [waking-label]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PEERS_ENV="$SCRIPT_DIR/keys/peers.env"
LOG_FILE="$SCRIPT_DIR/peer/logs/peer_health.jsonl"
STATE_FILE="$SCRIPT_DIR/peer/logs/peer_health_state.json"
LABEL="${1:-}"

if [[ ! -f "$PEERS_ENV" ]]; then
    echo "Missing $PEERS_ENV" >&2
    exit 1
fi

mkdir -p "$SCRIPT_DIR/peer/logs"
[[ -f "$STATE_FILE" ]] || echo '{}' > "$STATE_FILE"

# All peer names we hold a token for (SELF_NAME's own block excluded).
mapfile -t PEER_NAMES < <(grep -oP '^NAME=\K.*' "$PEERS_ENV" | grep -v '^BEACON$')

RESULTS_JSON="[]"
for NAME in "${PEER_NAMES[@]}"; do
    TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if "$SCRIPT_DIR/send_to_peer.sh" "$NAME" "beacon ${LABEL} routine credentialed health-check ${TS}" "health_check" >/tmp/peer_health_$$.out 2>&1; then
        REACHABLE=true
    else
        REACHABLE=false
    fi
    RESP="$(cat /tmp/peer_health_$$.out 2>/dev/null | tr -d '\n')"
    rm -f /tmp/peer_health_$$.out

    ENTRY="$(python3 -c '
import json, sys
name, ts, reachable, resp = sys.argv[1], sys.argv[2], sys.argv[3] == "true", sys.argv[4]
print(json.dumps({"peer": name, "time": ts, "reachable": reachable, "response": resp[:200]}))
' "$NAME" "$TS" "$REACHABLE" "$RESP")"
    echo "$ENTRY" >> "$LOG_FILE"
    RESULTS_JSON="$(python3 -c '
import json, sys
results = json.loads(sys.argv[1])
results.append(json.loads(sys.argv[2]))
print(json.dumps(results))
' "$RESULTS_JSON" "$ENTRY")"
    echo "$NAME: reachable=$REACHABLE"
done

# Update consecutive-miss streaks and report any peer now at >=3.
python3 -c '
import json, sys
state = json.load(open(sys.argv[1]))
results = json.loads(sys.argv[2])
escalate = []
for r in results:
    name = r["peer"]
    if r["reachable"]:
        state[name] = 0
    else:
        state[name] = state.get(name, 0) + 1
    if state[name] >= 3:
        escalate.append((name, state[name]))
json.dump(state, open(sys.argv[1], "w"), indent=2)
if escalate:
    print("ESCALATE: " + ", ".join(f"{n} ({c} misses in a row)" for n, c in escalate))
' "$STATE_FILE" "$RESULTS_JSON"
