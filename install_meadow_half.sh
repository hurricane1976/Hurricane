#!/usr/bin/env bash
# w496: install meadow's fresh sibling half into one sibling listener config.
# Usage: ./install_meadow_half.sh <HIGHBEAM|LANTERN|LIGHTNING|RADAR> <inbox-json-path>
# Tokens are never echoed. Append-don't-replace (w490/w493 precedent).
set -euo pipefail

SIBLING="${1:?sibling name required}"
JSON="${2:?inbox json path required}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PEERS_ENV="$SCRIPT_DIR/keys/peers.env"

case "$SIBLING" in
    HIGHBEAM)  CFG="$SCRIPT_DIR/peer/config/highbeam.env";   SVC=beacon-mesh-highbeam ;;
    LANTERN)   CFG="$SCRIPT_DIR/peer/config/lantern.env";    SVC=beacon-mesh-lantern ;;
    LIGHTNING) CFG="$SCRIPT_DIR/peer/config/lightning.env";  SVC=beacon-mesh-lightning ;;
    RADAR)     CFG="/home/agent/radar/keys/inbound.env";     SVC=radar-mesh ;;
    *) echo "unknown sibling: $SIBLING" >&2; exit 1 ;;
esac

TOKEN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["body"].strip())' "$JSON")"
if ! printf '%s' "$TOKEN" | grep -qE '^[0-9a-fA-F]{40,128}$'; then
    echo "FAIL: token from $JSON failed charset/length validation (len $(printf '%s' "$TOKEN" | wc -c))" >&2
    exit 1
fi
TOKEN_LEN="$(printf '%s' "$TOKEN" | wc -c | tr -d ' ')"

# Listener address: take it from an existing NAME=$SIBLING block (its ADDR is
# the sibling listener endpoint and does not change with this install).
ADDR=""
in_block=""
while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
    key="${line%%=*}"; val="${line#*=}"
    case "$key" in
        NAME) in_block=""; [[ "$val" == "$SIBLING" ]] && in_block=1 ;;
        ADDR) [[ "$in_block" == 1 ]] && ADDR="$val" ;;
    esac
done < "$PEERS_ENV"
if [[ -z "$ADDR" ]]; then echo "FAIL: no ADDR for $SIBLING in peers.env" >&2; exit 1; fi

# Idempotence guard: already installed?
if grep -qF "TOKEN=$TOKEN" "$CFG"; then
    echo "$SIBLING: fresh half already present in $(basename "$CFG"); skipping append"
else
    [[ -f "$CFG.bak-pre-meadowfresh-w496" ]] || cp -p "$CFG" "$CFG.bak-pre-meadowfresh-w496"
    {
        echo ""
        echo "# meadow fresh-mint half (w496 install; josh 15-green directive 22:29:14Z;"
        echo "# w477 NAME=MEADOW block above retired by meadow 21:48:59Z install - kept append-style)"
        echo "NAME=MEADOW"
        echo "ADDR=100.91.42.51:8791"
        echo "TOKEN=$TOKEN"
    } >> "$CFG"
    echo "$SIBLING: appended fresh MEADOW half (len $TOKEN_LEN) to $(basename "$CFG") (backup: $(basename "$CFG").bak-pre-meadowfresh-w496)"
fi

sudo -n systemctl restart "$SVC"
sleep 1
systemctl is-active "$SVC" >/dev/null || { echo "FAIL: $SVC not active after restart" >&2; exit 1; }
echo "$SIBLING: $SVC restarted, active"

HTTP="$(curl -fsS -m 15 -X POST "http://${ADDR}/inbox" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c '
import json, sys
print(json.dumps({"subject": "meadow-fresh-install labeled self-test (sent by Beacon as MEADOW, w496)", "body": "Beacon w496 install verification for the fresh MEADOW->'"$SIBLING"' half (josh 15-green directive 22:29:14Z): your listener now accepts the fresh-mint token. No reply needed."}))
')" -o /tmp/opencode/selftest-$SIBLING.json -w '%{http_code}' 2>&1)" || true
echo "$SIBLING: labeled self-test -> HTTP $HTTP: $(cat /tmp/opencode/selftest-$SIBLING.json 2>/dev/null || echo '(no body)')"
