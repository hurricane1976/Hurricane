# Ask josh

## Open

- **Telegram credentials needed.** `keys/telegram.env` is still a blank
  template (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID both empty). I cannot
  send any Telegram message, including the standard end-of-session
  notify, until these are filled in. To fix: create a bot via @BotFather,
  message it once, then fill in the two values in
  `/home/agent/agent/keys/telegram.env` (mode 600, already gitignored).
  I'll pick up the values automatically next waking — no need to tell me
  in any special way, just edit the file on the box.
