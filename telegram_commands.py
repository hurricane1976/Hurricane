#!/usr/bin/env python3
"""Dynamic Telegram command handler for Beacon.

Single consumer of the bot's getUpdates stream (runs every few minutes from
cron via telegram_commands.sh). For each new message *from josh's exact chat
id*:

  * "/<cmd> ..."  -> the leading token is exact-matched against a fixed
    allowlist (HANDLERS). Matched: run the mapped handler, send its output
    back. Unmatched: reply with /help. Message text is NEVER passed to a
    shell -- handlers run fixed argv lists.
  * anything else -> appended to .telegram_incoming so the next waking's
    check_replies.sh surfaces it, and josh gets a "logged" acknowledgement.

Security boundary (per the model Beacon recommended to Tidal, w145):
  - hard chat-id gate: msg.chat.id AND msg.from.id must both equal
    TELEGRAM_CHAT_ID, else the update is ignored entirely.
  - the command set is a closed dict; the first whitespace token is matched
    literally (after stripping a leading '/' and any '@botname' suffix).
  - no eval, no shell=True, no interpolation of inbound text into commands.
  - optional numeric args are parsed with int() and clamped.

Env (exported by telegram_commands.sh): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
"""
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
OFFSET_FILE = os.path.join(DIR, ".telegram_offset")
INCOMING_FILE = os.path.join(DIR, ".telegram_incoming")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

API = f"https://api.telegram.org/bot{TOKEN}"
MAX_MSG = 3800          # keep well under Telegram's 4096 hard limit
UNITS = ["nginx", "beacon-api", "beacon-peer", "fail2ban", "cron", "certbot.timer"]


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def run(argv, timeout=20):
    """Run a fixed argv list, return stripped stdout (stderr folded in)."""
    try:
        p = subprocess.run(argv, cwd=DIR, capture_output=True, text=True,
                           timeout=timeout)
        return (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return f"(timed out after {timeout}s)"
    except Exception as e:  # noqa: BLE001 - report, don't crash the poller
        return f"(error: {e})"


def tg_get(method, params=None):
    url = f"{API}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def send(text):
    text = text.strip() or "(no output)"
    if len(text) > MAX_MSG:
        text = text[:MAX_MSG] + "\n… (truncated)"
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text}).encode()
    try:
        with urllib.request.urlopen(f"{API}/sendMessage", data=data, timeout=30):
            pass
    except Exception as e:  # noqa: BLE001
        print(f"send failed: {e}")


def read_offset():
    try:
        with open(OFFSET_FILE) as f:
            return int(f.read().strip() or 0)
    except (FileNotFoundError, ValueError):
        return 0


def write_offset(n):
    with open(OFFSET_FILE, "w") as f:
        f.write(str(n))


# --------------------------------------------------------------------------
# command handlers -- each takes the raw arg string, returns text
# --------------------------------------------------------------------------
def cmd_help(_arg):
    return (
        "Beacon commands (josh only):\n"
        "/status   git sync, services, disk, uptime, live HTTP\n"
        "/health   alias for /status\n"
        "/notes    the latest NOTES.md entry\n"
        "/ask      the open items in ASK.md\n"
        "/watchdog run the health watchdog now, report result\n"
        "/digest   send the world-news + weather digest now\n"
        "/wake     trigger a wake.sh session now (no-ops if one is running)\n"
        "/help     this list\n"
        "Anything that isn't a command is logged for the next waking."
    )


def cmd_status(_arg):
    lines = []

    head = run(["git", "rev-parse", "--short", "HEAD"])
    run(["git", "fetch", "-q", "origin"], timeout=30)
    upstream = run(["git", "rev-parse", "--short", "@{u}"])
    behind_ahead = run(["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"])
    dirty = run(["git", "status", "--porcelain"])
    sync = "in sync" if head and head == upstream else f"HEAD {head} vs upstream {upstream}"
    lines.append(f"git: {sync} ({behind_ahead} ahead/behind)"
                 + ("" if not dirty else f"; {len(dirty.splitlines())} uncommitted"))

    svc_bad = []
    for s in UNITS:
        if run(["systemctl", "is-active", s]) != "active":
            svc_bad.append(s)
    lines.append("services: all active" if not svc_bad
                 else "services DOWN: " + ", ".join(svc_bad))

    try:
        import shutil
        du = shutil.disk_usage("/")
        pct = round(du.used / du.total * 100)
        free_gb = round(du.free / 1e9)
        lines.append(f"disk: {pct}% used, {free_gb}G free")
    except Exception:  # noqa: BLE001
        pass

    try:
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        d, rem = divmod(int(up), 86400)
        h = rem // 3600
        with open("/proc/loadavg") as f:
            load = f.read().split()[0]
        lines.append(f"uptime: {d}d {h}h, load {load}")
    except Exception:  # noqa: BLE001
        pass

    if os.path.exists("/var/run/reboot-required"):
        lines.append("reboot-required: SET")

    for path in ["/", "/status.html"]:
        code = run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                    "--max-time", "10", "--resolve",
                    "www.beaconwake.com:443:127.0.0.1",
                    f"https://www.beaconwake.com{path}"])
        lines.append(f"HTTP {path} -> {code}")

    return "beacon status\n" + "\n".join(lines)


def cmd_notes(_arg):
    path = os.path.join(DIR, "NOTES.md")
    with open(path) as f:
        text = f.read()
    idx = text.rfind("\n## ")
    entry = text[idx:].strip() if idx != -1 else text[-MAX_MSG:]
    if len(entry) > MAX_MSG:
        entry = entry[:MAX_MSG] + "\n… (entry truncated)"
    return entry


def cmd_ask(_arg):
    path = os.path.join(DIR, "ASK.md")
    with open(path) as f:
        text = f.read()
    start = text.find("## Open")
    if start == -1:
        return "(no '## Open' section in ASK.md)"
    nxt = text.find("\n## ", start + 1)
    return text[start:nxt].strip() if nxt != -1 else text[start:].strip()


def cmd_watchdog(_arg):
    run(["./watchdog.sh"], timeout=90)
    last = run(["tail", "-n", "1", "logs/watchdog.log"])
    return f"watchdog ran.\n{last}"


def cmd_digest(_arg):
    return run(["./digest.sh"], timeout=40)


def cmd_wake(_arg):
    try:
        subprocess.Popen(["./wake.sh"], cwd=DIR,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return ("wake.sh triggered. It holds a flock, so if a session is "
                "already running this call is a no-op (logged to "
                "logs/wake-skipped.log).")
    except Exception as e:  # noqa: BLE001
        return f"(failed to start wake.sh: {e})"


HANDLERS = {
    "help": cmd_help,
    "status": cmd_status,
    "health": cmd_status,
    "notes": cmd_notes,
    "ask": cmd_ask,
    "watchdog": cmd_watchdog,
    "digest": cmd_digest,
    "wake": cmd_wake,
}


# --------------------------------------------------------------------------
def log_incoming(date_epoch, text):
    with open(INCOMING_FILE, "a") as f:
        f.write(f"[{date_epoch}] {text}\n")


def handle_message(msg):
    frm = msg.get("from", {}) or {}
    if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
        return
    if str(frm.get("id")) != str(CHAT_ID):
        return  # chat id right but sender isn't josh -- ignore
    text = (msg.get("text") or "").strip()
    if not text:
        return

    if text.startswith("/"):
        token = text.split()[0][1:].split("@")[0].lower()
        arg = text[len(text.split()[0]):].strip()
        handler = HANDLERS.get(token)
        if handler:
            print(f"cmd: /{token}")
            send(handler(arg))
        else:
            send(f"unknown command '/{token}'.\n\n" + cmd_help(""))
        return

    # not a command -> queue for the next waking
    log_incoming(msg.get("date", int(time.time())), text)
    send("Logged for the next waking. Send /help for commands.")


def main():
    if not TOKEN or not CHAT_ID:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
        return
    offset = read_offset()
    try:
        data = tg_get("getUpdates", {"offset": offset + 1, "timeout": 0})
    except Exception as e:  # noqa: BLE001
        print(f"getUpdates failed: {e}")
        return
    if not data.get("ok"):
        print(f"getUpdates not ok: {data}")
        return

    max_id = None
    for upd in data.get("result", []):
        max_id = upd["update_id"]
        msg = upd.get("message") or upd.get("edited_message")
        if msg:
            try:
                handle_message(msg)
            except Exception as e:  # noqa: BLE001 - one bad msg shouldn't wedge the loop
                print(f"handle_message error: {e}")
    if max_id is not None:
        write_offset(max_id)


if __name__ == "__main__":
    main()
