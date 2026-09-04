#!/usr/bin/env python3
"""One-time / idempotent head-meta injector.

Adds two lines to every page's <head>, right after the apple-touch-icon link:

    <meta name="theme-color" content="#0a0d13">
    <link rel="manifest" href="/site.webmanifest">

`theme-color` tints the mobile browser chrome to match the page background
(--bg in style.css); the manifest link makes the site installable. Both are
inert on browsers that don't use them.

There is no shared <head> for the hand-written pages, so this is the same
approach localize_fonts.py used for the font <link>: run once to migrate,
re-run any time (it's idempotent -- it skips a file that already has the
theme-color meta). The 6 *.template.html files are edited too so the
generated pages (log/weekly/roadmap/status/fleet-status/metrics) keep it.

smoke_test.py --local asserts every *.html carries the meta, so a new page
that forgets it fails the gate.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ANCHOR = '<link rel="apple-touch-icon" href="/apple-touch-icon.png">'
INJECT = (
    '<meta name="theme-color" content="#0a0d13">\n'
    '<link rel="manifest" href="/site.webmanifest">'
)


def process(path: Path) -> bool:
    text = path.read_text()
    if 'name="theme-color"' in text:
        return False
    if ANCHOR not in text:
        print(f"  !! {path.name}: no apple-touch-icon anchor, skipped")
        return False
    path.write_text(text.replace(ANCHOR, ANCHOR + "\n" + INJECT, 1))
    return True


def main() -> None:
    targets = sorted(HERE.glob("*.html")) + sorted(HERE.glob("*.template.html"))
    changed = 0
    for f in targets:
        if process(f):
            print(f"  ++ {f.name}")
            changed += 1
    print(f"add_head_meta: {changed} file(s) updated, {len(targets) - changed} already current")


if __name__ == "__main__":
    main()
