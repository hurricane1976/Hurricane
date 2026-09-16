#!/usr/bin/env bash
# Send a message to a configured peer Beacon agent's inbox.
# Usage: ./send_to_peer.sh [--to <agent>] <peer-name> "message body" ["subject"]
#
# --to <agent> addresses the message at a named sibling on the peer's box, so
# it lands in that box's peer/inbox/<agent>/ instead of the shared root. The
# peer's listener validates the name; an unknown/malformed one is filed to the
# peer's root inbox, never bounced. Omitting --to is unchanged behaviour.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PEERS_ENV="$SCRIPT_DIR/keys/peers.env"

TO=""
while [[ "${1:-}" == --* ]]; do
    case "$1" in
        --to) TO="${2:-}"; shift 2 ;;
        --) shift; break ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 [--to <agent>] <peer-name> \"message body\" [\"subject\"]" >&2
    exit 1
fi

PEER_NAME="$1"
BODY="$2"
SUBJECT="${3:-}"

if [[ ! -f "$PEERS_ENV" ]]; then
    echo "Missing $PEERS_ENV -- copy keys/peers.env.example and fill it in." >&2
    exit 1
fi

# Parse keys/peers.env: find the NAME=<PEER_NAME> block and read its ADDR/TOKEN.
# A new NAME= line always resets which block we're in, so blocks don't need
# blank-line separation to parse correctly.
ADDR=""
TOKEN=""
in_block=""
while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    case "$key" in
        NAME)
            in_block=""
            [[ "$val" == "$PEER_NAME" ]] && in_block="1"
            ;;
        ADDR) [[ "$in_block" == "1" ]] && ADDR="$val" ;;
        TOKEN) [[ "$in_block" == "1" ]] && TOKEN="$val" ;;
    esac
done < "$PEERS_ENV"

if [[ -z "$ADDR" || -z "$TOKEN" ]]; then
    echo "No peer named '$PEER_NAME' found in $PEERS_ENV" >&2
    exit 1
fi

PAYLOAD="$(python3 -c '
import json, sys
msg = {"subject": sys.argv[1], "body": sys.argv[2]}
if sys.argv[3]:
    msg["to"] = sys.argv[3]
print(json.dumps(msg))
' "$SUBJECT" "$BODY" "$TO")"

curl -fsS -m 15 -X POST "http://${ADDR}/inbox" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD"

# w452: best-effort outbound send record for /api/packets + /packets.html
# (metadata only; kind is classified from the subject, never the raw text).
# Never fatal: a logging failure must not fail the send itself.
LOGDIR="$SCRIPT_DIR/peer/logs"
mkdir -p "$LOGDIR" 2>/dev/null || true
PACKET_BYTES="$(printf '%s' "$PAYLOAD" | wc -c | tr -d ' ')"
PACKET_KIND="$(python3 - "$SUBJECT" <<'PYEOF' 2>/dev/null || echo message
import sys
s = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
if not s: print("message")
elif "health_check" in s or "health-check" in s: print("health-check")
elif any(w in s for w in ("verify", "probe", "latency", "link check")): print("link-verification")
elif "agora" in s or "bridge" in s: print("bridge")
elif any(w in s for w in ("rotation", "token", "credential")): print("credentials")
elif any(w in s for w in ("sweep", "digest", "report")): print("sweep-note")
else: print("message")
PYEOF
)"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) OUT to=${PEER_NAME} bytes=${PACKET_BYTES} kind='${PACKET_KIND}'" \
    >> "$LOGDIR/peer_send.log" 2>/dev/null || true

echo
