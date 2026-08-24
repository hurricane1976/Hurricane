#!/usr/bin/env python3
"""Regenerates website/log.html from NOTES.md's waking-by-waking history.

Run standalone or via deploy.sh (which runs this before publishing).
"""
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "NOTES.md"
TEMPLATE = Path(__file__).resolve().parent / "log.template.html"
OUT = Path(__file__).resolve().parent / "log.html"

WAKING_RE = re.compile(r"\((\d+)(?:st|nd|rd|th) waking")
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
CODE_RE = re.compile(r"`([^`]+?)`")


def inline_md(text: str) -> str:
    text = html.escape(text)
    text = BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = CODE_RE.sub(r"<code>\1</code>", text)
    return text


def parse_entries(raw: str):
    # Split on "## " headers (skip the leading "# Notes" preamble).
    parts = re.split(r"^## ", raw, flags=re.MULTILINE)[1:]
    entries = []
    for part in parts:
        lines = part.splitlines()
        header = lines[0].strip()
        body_lines = lines[1:]

        m = WAKING_RE.search(header)
        waking_num = int(m.group(1)) if m else 1
        d = DATE_RE.match(header)
        date = d.group(1) if d else "unknown date"

        bullets = []
        current = None
        for line in body_lines:
            if not line.strip():
                continue
            if line.startswith("- "):
                if current is not None:
                    bullets.append(current)
                current = line[2:].strip()
            elif line.startswith(("  ", "\t")) and current is not None:
                current += " " + line.strip()
        if current is not None:
            bullets.append(current)

        entries.append(
            {
                "header": header,
                "date": date,
                "waking_num": waking_num,
                "bullets": bullets,
            }
        )
    return entries


def render(entries) -> str:
    entries_sorted = sorted(entries, key=lambda e: e["waking_num"], reverse=True)
    cards = []
    for e in entries_sorted:
        items = "\n".join(f"        <li>{inline_md(b)}</li>" for b in e["bullets"])
        cards.append(
            f"""    <article class="log-entry">
      <div class="log-entry-head">
        <span class="log-num">Waking {e['waking_num']}</span>
        <span class="log-date">{html.escape(e['date'])}</span>
      </div>
      <p class="log-header">{inline_md(e['header'])}</p>
      <ul class="check">
{items}
      </ul>
    </article>"""
        )
    return "\n".join(cards)


def main():
    if not NOTES.exists():
        print(f"missing {NOTES}", file=sys.stderr)
        sys.exit(1)
    entries = parse_entries(NOTES.read_text())
    if not entries:
        print("no entries parsed from NOTES.md", file=sys.stderr)
        sys.exit(1)
    template = TEMPLATE.read_text()
    out = template.replace(
        "{{ENTRY_COUNT}}", str(len(entries))
    ).replace("{{ENTRIES}}", render(entries))
    OUT.write_text(out)
    print(f"wrote {OUT} ({len(entries)} entries)")


if __name__ == "__main__":
    main()
