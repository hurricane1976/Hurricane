#!/usr/bin/env python3
# Helper for check_replies.sh: filters getUpdates JSON on stdin to
# messages from your chat id, prints them, and persists the new offset.
import json
import sys

chat_id, offset_file = sys.argv[1], sys.argv[2]
data = json.load(sys.stdin)
results = data.get("result", [])

max_update_id = None
found = False
for upd in results:
    max_update_id = upd["update_id"]
    msg = upd.get("message")
    if not msg:
        continue
    if str(msg.get("chat", {}).get("id")) != str(chat_id):
        continue  # not your chat -- ignore per AGENT.md
    found = True
    print(f"[{msg.get('date')}] {msg.get('text', '<non-text message>')}")

if not found:
    print("(no new messages)")

if max_update_id is not None:
    with open(offset_file, "w") as f:
        f.write(str(max_update_id))
