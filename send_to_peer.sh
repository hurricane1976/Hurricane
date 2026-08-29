#!/usr/bin/env bash
# Send a message to a configured peer Beacon agent's inbox.
# Usage: ./send_to_peer.sh <peer-name> "message body" ["subject"]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PEERS_ENV="$SCRIPT_DIR/keys/peers.env"

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <peer-name> \"message body\" [\"subject\"]" >&2
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
print(json.dumps({"subject": sys.argv[1], "body": sys.argv[2]}))
' "$SUBJECT" "$BODY")"

curl -fsS -m 15 -X POST "http://${ADDR}/inbox" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD"
echo
