#!/usr/bin/env python3
"""w258 site-wide visual refresh — swap the shared <header> and .backdrop
markup on every hand-written / template page to the slim v2 shell that matches
the React front door (website/site/). Content, <head>, footers, page bodies
and every SVG diagram are left untouched; the look comes from style.css.

Idempotent: a page that already carries `class="site-header-v2"` is skipped.
Run once and commit; it also rewrites the *.template.html files so the
Python-generated pages (log/status/metrics/…) pick it up on their next build.

Not wired into deploy.sh — this is a one-time migration like add_head_meta.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The React-built pages (prerendered in website/site/) — never touch these.
REACT = {
    "index.html", "getting-started.html", "build.html", "field-guide.html",
    "faq.html", "guides.html", "study-guide.html", "memory-handbook.html",
    "get.html",
}
SKIP = REACT | {"newsletter.html"}

MARK = (
    '<svg viewBox="0 0 64 64" role="img" aria-label="Beacon mark">'
    '<circle cx="32" cy="32" r="22" fill="none" stroke="var(--teal)" stroke-width="2.5" opacity="0.32"/>'
    '<circle cx="32" cy="32" r="14" fill="none" stroke="var(--teal)" stroke-width="3" opacity="0.6"/>'
    '<circle cx="32" cy="32" r="7" fill="var(--amber)"/></svg>'
)

# Slim nav — a handful of anchors, matching the React SlimHeader intent but
# with the extra reach a content site needs.
NAV_LINKS = [
    ("/observability.html", "Observability"),
    ("/log.html", "Log"),
    ("/fleet-status.html", "Fleet"),
    ("/metrics.html", "Metrics"),
    ("/infrastructure.html", "Infrastructure"),
    ("/roadmap.html", "Roadmap"),
    ("/guides.html", "Guides"),
    ("/field-guide.html", "Field guide"),
    ("/faq.html", "FAQ"),
]
CTA = ("/get.html", "Get the editions")

BACKDROP_V2 = (
    '<div class="backdrop" aria-hidden="true">\n'
    '  <svg viewBox="0 0 600 600" preserveAspectRatio="xMidYMid slice">\n'
    '    <g>\n'
    '      <circle class="backdrop-ring" cx="300" cy="300" r="290"/>\n'
    '      <circle class="backdrop-ring" cx="300" cy="300" r="290"/>\n'
    '      <circle class="backdrop-ring" cx="300" cy="300" r="290"/>\n'
    '    </g>\n'
    '  </svg>\n'
    '</div>'
)

HEADER_RE = re.compile(r"<header\b(?![^>]*site-header-v2).*?</header>", re.S | re.I)
BACKDROP_RE = re.compile(r'<div class="backdrop"[^>]*>.*?</div>', re.S | re.I)
ACTIVE_RE = re.compile(r'<a[^>]*href="([^"]+)"[^>]*class="[^"]*\bactive\b')


def build_header(active_href: str | None) -> str:
    def norm(h: str) -> str:
        return h.split("#")[0].rstrip("/") or "/"

    a = norm(active_href) if active_href else None
    items = []
    for href, label in NAV_LINKS:
        cur = ' aria-current="page"' if a and norm(href) == a else ""
        items.append(f'    <a href="{href}"{cur}>{label}</a>')
    cta_cur = ' aria-current="page"' if a and a == norm(CTA[0]) else ""
    items.append(f'    <a href="{CTA[0]}" class="nav-v2-cta"{cta_cur}>{CTA[1]}</a>')
    nav = "\n".join(items)
    return (
        '<header class="site-header-v2">\n'
        f'  <a class="brand-v2" href="/">{MARK}Beacon</a>\n'
        '  <nav class="nav-v2" aria-label="Primary">\n'
        f'{nav}\n'
        '  </nav>\n'
        '</header>'
    )


def process(path: Path) -> bool:
    text = path.read_text()
    orig = text
    m = HEADER_RE.search(text)
    if m:
        am = ACTIVE_RE.search(m.group(0))
        text = text[: m.start()] + build_header(am.group(1) if am else None) + text[m.end():]
    text = BACKDROP_RE.sub(lambda _m: BACKDROP_V2, text, count=1)
    if text != orig:
        path.write_text(text)
        return True
    return False


def main() -> int:
    targets = sorted(HERE.glob("*.html")) + sorted(HERE.glob("*.template.html"))
    changed = 0
    for f in targets:
        if f.name in SKIP:
            continue
        if process(f):
            print(f"  ++ {f.name}")
            changed += 1
    print(f"restyle_shared: {changed} file(s) updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
