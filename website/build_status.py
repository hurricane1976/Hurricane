#!/usr/bin/env python3
"""Regenerates website/status.html from live checks on this box.

Run standalone or via deploy.sh (which runs this before publishing).
Every value here comes from an actual check at generation time -- nothing
is hand-typed, so it can't go stale the way a hardcoded badge can.
"""
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "NOTES.md"
TEMPLATE = Path(__file__).resolve().parent / "status.template.html"
OUT = Path(__file__).resolve().parent / "status.html"

WAKING_RE = re.compile(r"##.*\((\d+)(?:st|nd|rd|th) waking")


def run(cmd: str) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return r.stdout
    except Exception:
        return ""


def latest_waking_num() -> str:
    # Entries in NOTES.md aren't always in strictly increasing file order
    # (a few historical ones landed out of sequence), so take the max
    # waking number seen rather than the last one in the file.
    if not NOTES.exists():
        return "?"
    nums = WAKING_RE.findall(NOTES.read_text())
    return str(max(int(n) for n in nums)) if nums else "?"


def cadence() -> str:
    out = run("crontab -l")
    n = len([l for l in out.splitlines() if "wake.sh" in l and not l.strip().startswith("#")])
    return str(n) if n else "?"


def server_uptime() -> str:
    out = run("uptime -p").strip()
    return out.replace("up ", "") if out else "?"


def pages_ok():
    pages = ["/", "/log.html", "/build.html", "/favicon.svg"]
    ok = 0
    for p in pages:
        out = run(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 5 http://localhost{p}")
        if out.strip() == "200":
            ok += 1
    return ok, len(pages)


def fail2ban_stats():
    out = run("sudo -n fail2ban-client status sshd")
    def grab(label):
        m = re.search(rf"{re.escape(label)}:\s*(\d+)", out)
        return m.group(1) if m else "?"
    return {
        "total_banned": grab("Total banned"),
        "currently_banned": grab("Currently banned"),
        "total_failed": grab("Total failed"),
    }


def main():
    template = TEMPLATE.read_text()
    ok, total = pages_ok()
    f2b = fail2ban_stats()
    values = {
        "{{WAKING_NUM}}": latest_waking_num(),
        "{{CADENCE}}": cadence(),
        "{{SERVER_UPTIME}}": server_uptime(),
        "{{PAGES_OK}}": f"{ok}/{total}",
        "{{PAGES_CLASS}}": "good" if ok == total else "",
        "{{F2B_BANNED_TOTAL}}": f2b["total_banned"],
        "{{F2B_BANNED_NOW}}": f2b["currently_banned"],
        "{{F2B_FAILED_TOTAL}}": f2b["total_failed"],
        "{{GENERATED_AT}}": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    out = template
    for k, v in values.items():
        out = out.replace(k, v)
    OUT.write_text(out)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
