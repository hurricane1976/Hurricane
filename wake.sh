#!/usr/bin/env bash
# Cron entry point. Wakes the agent, hands it AGENT.md, logs the run.
cd /home/agent/agent || exit 1

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

mkdir -p logs
find logs -name '*.log' -mtime +30 -delete
TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="logs/${TS}.log"

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
CLAUDE_EXIT=$?

echo "exit code: $CLAUDE_EXIT" >>"$LOG_FILE"

# Republish the website's activity log from the fresh NOTES.md entry this
# session just wrote, so the public log page reflects reality without
# depending on the session remembering to redeploy manually.
if [ "$CLAUDE_EXIT" -eq 0 ]; then
    ./website/deploy.sh >>"$LOG_FILE" 2>&1 || echo "website deploy failed" >>"$LOG_FILE"
fi

# If the session itself crashed/errored, it may never have reached its own
# end-of-session notify.sh call -- that path only fires if the session runs
# to completion. Send a failure alert directly from the shell so a crash
# doesn't go silent until someone happens to check logs/.
if [ "$CLAUDE_EXIT" -ne 0 ]; then
    TAIL="$(tail -c 1500 "$LOG_FILE")"
    ./notify.sh "wake.sh: claude session exited with code $CLAUDE_EXIT ($TS). Log tail:
$TAIL" >>"$LOG_FILE" 2>&1
fi
