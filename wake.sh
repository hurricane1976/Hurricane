#!/usr/bin/env bash
# Cron entry point. Wakes the agent, hands it AGENT.md, logs the run.
cd /home/agent/agent || exit 1

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

mkdir -p logs
find logs -name '*.log' -mtime +30 -delete
TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="logs/${TS}.log"

# josh asked (via Telegram, 2026-08-24) for a digest every wake. Send it
# directly here rather than relying on the LLM session to remember.
if DIGEST="$(./digest.sh 5 2>>"$LOG_FILE")"; then
    ./notify.sh "$DIGEST" >>"$LOG_FILE" 2>&1 || echo "digest notify failed" >>"$LOG_FILE"
else
    echo "digest.sh failed" >>"$LOG_FILE"
fi

PROMPT="You are waking up on your regular schedule. Read /home/agent/AGENT.md \
first -- it has your operating rules; follow them. Check NOTES.md, ASK.md, \
and memory/ in this directory (/home/agent/agent) for prior context. Do \
whatever useful work seems worthwhile within AGENT.md's rules. Append a \
dated entry to NOTES.md summarizing what you did this waking. Before you \
finish, run ./notify.sh with a short summary of this session, per AGENT.md's \
'Keeping me posted' instruction."

claude -p "$PROMPT" \
    --permission-mode bypassPermissions \
    --add-dir /home/agent \
    --output-format text \
    >>"$LOG_FILE" 2>&1

echo "exit code: $?" >>"$LOG_FILE"
