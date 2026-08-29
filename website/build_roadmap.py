#!/usr/bin/env python3
"""Regenerates website/roadmap.html from ASK.md's Open/On hold/Resolved sections.

Run standalone or via deploy.sh (which runs this before publishing).
"""
import html
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASK = ROOT / "ASK.md"
TEMPLATE = Path(__file__).resolve().parent / "roadmap.template.html"
OUT = Path(__file__).resolve().parent / "roadmap.html"

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
CODE_RE = re.compile(r"`([^`]+?)`")
# Matches placeholder items a waking might drop into an empty ASK.md section,
# e.g. "(none)", "_(nothing open)_", "*nothing here yet*" — so the roadmap
# renders the friendly "nothing open" copy instead of a literal bullet.
EMPTY_ITEM_RE = re.compile(r"^[_*\s()]*(none|nothing\b.*?)[_*\s()]*$", re.IGNORECASE)


def section_is_empty(items) -> bool:
    return not items or all(EMPTY_ITEM_RE.match(i) for i in items)


def inline_md(text: str) -> str:
    text = html.escape(text)
    text = BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = CODE_RE.sub(r"<code>\1</code>", text)
    return text


def parse_sections(raw: str):
    # Split on "## " headers (skip the leading "# Ask josh" preamble).
    parts = re.split(r"^## ", raw, flags=re.MULTILINE)[1:]
    sections = {}
    for part in parts:
        lines = part.splitlines()
        name = lines[0].strip()
        items = []
        current = None
        for line in lines[1:]:
            if line.startswith("- "):
                if current is not None:
                    items.append(current.strip())
                current = line[2:].strip()
            elif not line.strip():
                continue
            elif current is not None:
                current += " " + line.strip()
        if current is not None:
            items.append(current.strip())
        sections[name] = items
    return sections


def items_html(items) -> str:
    return "\n".join(f"        <li>{inline_md(i)}</li>" for i in items)


def main():
    if not ASK.exists():
        print(f"missing {ASK}", file=sys.stderr)
        sys.exit(1)
    sections = parse_sections(ASK.read_text())
    open_items = sections.get("Open", [])
    on_hold_items = sections.get("On hold", [])
    resolved_items = sections.get("Resolved", [])

    if section_is_empty(open_items):
        open_body = '      <p>Nothing open right now &mdash; no pending questions waiting on josh.</p>'
    else:
        open_body = f'      <ul class="check">\n{items_html(open_items)}\n      </ul>'

    if section_is_empty(on_hold_items):
        on_hold_body = '      <p>Nothing on hold right now.</p>'
    else:
        on_hold_body = f'      <ul class="check">\n{items_html(on_hold_items)}\n      </ul>'

    template = TEMPLATE.read_text()
    out = (
        template.replace("{{OPEN_BODY}}", open_body)
        .replace("{{ON_HOLD_BODY}}", on_hold_body)
        .replace("{{RESOLVED_COUNT}}", str(len(resolved_items)))
        .replace(
            "{{GENERATED_AT}}",
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )
    )
    OUT.write_text(out)
    open_n = 0 if section_is_empty(open_items) else len(open_items)
    on_hold_n = 0 if section_is_empty(on_hold_items) else len(on_hold_items)
    print(f"wrote {OUT} ({open_n} open, {on_hold_n} on hold, {len(resolved_items)} resolved)")


if __name__ == "__main__":
    main()
