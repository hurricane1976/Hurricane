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

WAKING_RE = re.compile(r"(\d+)(?:st|nd|rd|th) waking")
WNUM_RE = re.compile(r"^w(\d{2,4})\b")
SUBHEAD_RE = re.compile(r"^### +(w\d{2,4}\b.*)$")
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
CODE_RE = re.compile(r"`([^`]+?)`")


def inline_md(text: str) -> str:
    text = html.escape(text)
    text = BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = CODE_RE.sub(r"<code>\1</code>", text)
    return text


def _waking_num(header: str):
    m = WAKING_RE.search(header)
    if m:
        return int(m.group(1))
    m = WNUM_RE.match(header)
    if m:
        return int(m.group(1))
    return None


def _bullets(body_lines):
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
    return bullets


def parse_entries(raw: str):
    # Split on "## " headers (skip the leading "# Notes" preamble).
    parts = re.split(r"^## ", raw, flags=re.MULTILINE)[1:]
    entries = []
    for part in parts:
        lines = part.splitlines()
        header = lines[0].strip()
        body_lines = lines[1:]

        d = DATE_RE.match(header)
        date = d.group(1) if d else "unknown date"
        hdr_num = _waking_num(header) or 1

        # Since w257, interactive/josh-directed wakings are logged as
        # "### wNNN — ..." subsections nested under one dated "## " header.
        # Treat each subsection as its own waking, inheriting the enclosing
        # date; prose before the first subsection stays with the "## " header.
        sub_starts = [i for i, ln in enumerate(body_lines) if SUBHEAD_RE.match(ln)]
        if sub_starts:
            segments = [(header, hdr_num, body_lines[: sub_starts[0]])]
            for j, s in enumerate(sub_starts):
                nxt = sub_starts[j + 1] if j + 1 < len(sub_starts) else len(body_lines)
                sub_hdr = SUBHEAD_RE.match(body_lines[s]).group(1).strip()
                segments.append((sub_hdr, _waking_num(sub_hdr) or hdr_num,
                                 body_lines[s + 1:nxt]))
        else:
            segments = [(header, hdr_num, body_lines)]

        for seg_header, seg_num, seg_body in segments:
            entries.append(
                {
                    "header": seg_header,
                    "date": date,
                    "waking_num": seg_num,
                    "bullets": _bullets(seg_body),
                }
            )

    # Fold entries that share a waking number (e.g. a "257th waking" section
    # plus a later "### w257 cont." subsection) into one, keeping the first
    # header and concatenating bullets.
    merged, order = {}, []
    for e in entries:
        n = e["waking_num"]
        if n in merged:
            merged[n]["bullets"].extend(e["bullets"])
        else:
            merged[n] = e
            order.append(n)
    return [merged[n] for n in order]


def render(entries) -> str:
    entries_sorted = sorted(entries, key=lambda e: e["waking_num"], reverse=True)
    cards = []
    for e in entries_sorted:
        items = "\n".join(f"        <li>{inline_md(b)}</li>" for b in e["bullets"])
        cards.append(
            f"""    <article class="log-entry" id="waking-{e['waking_num']}">
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
