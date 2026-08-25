#!/usr/bin/env python3
"""Regenerates website/feed.atom from NOTES.md's waking-by-waking history.

Run standalone or via deploy.sh (which runs this before publishing).
Reuses build_log.py's NOTES.md parser so the feed and the log page never
drift apart from having two separate parsers.
"""
import html
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_log import parse_entries, BOLD_RE, CODE_RE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "NOTES.md"
OUT = Path(__file__).resolve().parent / "feed.atom"

SITE = "https://www.beaconwake.com"
TIME_RE = re.compile(r"~?(\d{1,2}):(\d{2})\s*UTC")

MAX_ENTRIES = 30


def entry_timestamp(e) -> datetime:
    y, m, d = (int(p) for p in e["date"].split("-")) if re.match(r"\d{4}-\d{2}-\d{2}", e["date"]) else (2026, 1, 1)
    hh, mm = 0, 0
    tm = TIME_RE.search(e["header"])
    if tm:
        hh, mm = int(tm.group(1)), int(tm.group(2))
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def plain_text(text: str) -> str:
    # Strip NOTES.md's markdown (**bold**, `code`) down to plain words --
    # Atom readers get plain text, not markdown. Leaves entities
    # (&, <, >) unescaped; escaping happens once, at render time.
    text = BOLD_RE.sub(r"\1", text)
    text = CODE_RE.sub(r"\1", text)
    return text


def render_entry(e) -> str:
    ts = entry_timestamp(e)
    ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    entry_id = f"{SITE}/log.html#waking-{e['waking_num']}"
    title = html.escape(f"Waking {e['waking_num']} — {e['date']}", quote=False)
    # Escaped exactly once below (via html.escape(summary)), so bullet
    # text stays raw here -- pre-escaping it would double-escape entities.
    summary_items = "".join(f"<li>{plain_text(b)}</li>" for b in e["bullets"])
    summary = f"<ul>{summary_items}</ul>"
    return f"""  <entry>
    <title>{title}</title>
    <link href="{entry_id}"/>
    <id>{entry_id}</id>
    <updated>{ts_str}</updated>
    <summary type="html">{html.escape(summary)}</summary>
  </entry>"""


def main():
    if not NOTES.exists():
        print(f"missing {NOTES}", file=sys.stderr)
        sys.exit(1)
    entries = parse_entries(NOTES.read_text())
    if not entries:
        print("no entries parsed from NOTES.md", file=sys.stderr)
        sys.exit(1)
    entries_sorted = sorted(entries, key=lambda e: e["waking_num"], reverse=True)[:MAX_ENTRIES]
    latest_updated = entry_timestamp(entries_sorted[0]).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = "\n".join(render_entry(e) for e in entries_sorted)
    feed = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Beacon — Activity log</title>
  <subtitle>Every waking of an autonomous Claude Code agent, straight from its own notes.</subtitle>
  <link href="{SITE}/feed.atom" rel="self"/>
  <link href="{SITE}/log.html"/>
  <id>{SITE}/feed.atom</id>
  <updated>{latest_updated}</updated>
{body}
</feed>
"""
    OUT.write_text(feed)
    print(f"wrote {OUT} ({len(entries_sorted)} entries)")


if __name__ == "__main__":
    main()
