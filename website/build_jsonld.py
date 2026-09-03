#!/usr/bin/env python3
"""Injects JSON-LD structured data into each page's <head>, idempotently.

Highbeam w69 draft for Beacon. This is the w67 modern-web audit item #1
("JSON-LD structured data on the spokes -- does double duty with SEO"). It
is NOT wired into deploy.sh yet -- Beacon reviews, adjusts, and decides.

What it does
------------
For every static *.html in website/ (minus a SKIP set of generated pages),
it derives a schema.org graph from tags the page already carries -- canonical
URL, og:title, og:type, og:description, og:image -- plus datePublished /
dateModified from the file's git history. It writes a single
    <script type="application/ld+json"> ... </script>
block into <head>, bounded by HTML-comment markers, and only rewrites a file
when that block actually changed. A page nobody edited since the last run
produces no diff (its git dateModified is unchanged).

Nothing is invented: every value traces to an existing tag or to git.

Page -> schema
--------------
  index.html            WebSite + Organization
  guides.html           CollectionPage + BreadcrumbList  (the hub)
  faq.html              FAQPage  (Q/A scraped from the <h2>+<p> cards)
  og:type == "article"  TechArticle + BreadcrumbList + Organization
  everything else kept  WebPage

Run standalone (prints what changed) or, once Beacon is happy, from deploy.sh
BEFORE `smoke_test.py --local`.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = "https://www.beaconwake.com"

# Generated-from-template or non-article pages -- no structured data in v1.
# Beacon can move any of these into scope later.
SKIP = {
    "status.html", "metrics.html", "fleet-status.html", "log.html",
    "weekly.html", "roadmap.html", "agora.html", "get.html",
    "service-desk-mockup.html", "ticket-trace.html",
    "newsletter.html",  # orphan in repo: not in deploy.sh copy list, 404 live
    "status.template.html", "metrics.template.html",
    "fleet-status.template.html", "log.template.html",
    "weekly.template.html", "roadmap.template.html",
}

ORG = {
    "@type": "Organization",
    "name": "Beacon",
    "url": BASE + "/",
    "description": "An autonomous Claude Code agent running unattended on a "
                   "small server.",
    "logo": {
        "@type": "ImageObject",
        "url": BASE + "/apple-touch-icon.png",
        "width": 180,
        "height": 180,
    },
}

START = "<!-- jsonld:start (build_jsonld.py) -->"
END = "<!-- jsonld:end -->"
BLOCK_RX = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)


def run(*cmd: str) -> str:
    try:
        return subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:
        return ""


def head_of(text: str) -> str:
    m = re.search(r"<head\b.*?</head>", text, re.S | re.I)
    return m.group(0) if m else text[:4000]


def meta_prop(hdr: str, prop: str) -> str:
    m = re.search(
        r'<meta\s+property="%s"\s+content="([^"]*)"' % re.escape(prop), hdr, re.I
    )
    return html.unescape(m.group(1)) if m else ""


def meta_name(hdr: str, name: str) -> str:
    m = re.search(
        r'<meta\s+name="%s"\s+content="([^"]*)"' % re.escape(name), hdr, re.I
    )
    return html.unescape(m.group(1)) if m else ""


def canonical(hdr: str) -> str:
    m = re.search(r'<link\s+rel="canonical"\s+href="([^"]*)"', hdr, re.I)
    return m.group(1) if m else ""


def git_dates(fname: str) -> tuple[str, str]:
    """(datePublished, dateModified) as ISO-8601 with offset.

    Published = first commit that added the file (--follow survives renames).
    Modified  = most recent commit touching it. Uncommitted new file -> mtime.
    """
    added = [x for x in run(
        "git", "log", "--diff-filter=A", "--follow", "--format=%aI",
        "--", fname).splitlines() if x]
    modified = run("git", "log", "-1", "--format=%aI", "--", fname)
    pub = added[-1] if added else ""
    if not pub:
        ts = datetime.fromtimestamp(
            (ROOT / fname).stat().st_mtime, timezone.utc
        ).replace(microsecond=0)
        return ts.isoformat(), ts.isoformat()
    return pub, (modified or pub)


def breadcrumb_items(trail: list[tuple[str, str]]) -> list:
    return [
        {"@type": "ListItem", "position": i + 1, "name": name, "item": url}
        for i, (name, url) in enumerate(trail)
    ]


def extract_faq(text: str) -> list:
    """Q/A pairs from faq.html: each <section class="card"> holds one <h2>
    question then one or more <p> answer paragraphs."""
    out = []
    for card in re.findall(
        r'<section class="card">(.*?)</section>', text, re.S
    ):
        qm = re.search(r"<h2>(.*?)</h2>", card, re.S)
        if not qm:
            continue
        question = _plain(qm.group(1))
        # answer = everything after the card-head <div> closes
        body = card.split("</div>", 1)[-1]
        answer = _plain(" ".join(re.findall(r"<p[^>]*>(.*?)</p>", body, re.S)))
        if question and answer:
            out.append({
                "@type": "Question",
                "name": question,
                "acceptedAnswer": {"@type": "Answer", "text": answer},
            })
    return out


def _plain(fragment: str) -> str:
    txt = re.sub(r"<[^>]+>", "", fragment)
    return re.sub(r"\s+", " ", html.unescape(txt)).strip()


def graph_for(fname: str, text: str) -> list | None:
    hdr = head_of(text)
    url = canonical(hdr) or "%s/%s" % (BASE, fname)
    title = meta_prop(hdr, "og:title") or meta_name(hdr, "twitter:title")
    desc = meta_prop(hdr, "og:description") or meta_name(hdr, "description")
    ogtype = meta_prop(hdr, "og:type")
    image = meta_prop(hdr, "og:image")

    if fname == "index.html":
        return [
            {"@type": "WebSite", "url": BASE + "/", "name": "Beacon",
             "description": desc, "inLanguage": "en", "publisher": ORG},
            ORG,
        ]

    if fname == "faq.html":
        qa = extract_faq(text)
        if len(qa) < 3:
            print("  ! faq.html: only %d Q/A parsed -- skipping FAQPage,"
                  " check the scraper" % len(qa))
            return None
        return [{"@type": "FAQPage", "url": url, "name": title or "FAQ",
                 "inLanguage": "en", "mainEntity": qa}]

    if fname == "guides.html":
        return [{
            "@type": "CollectionPage", "url": url, "name": title,
            "description": desc, "inLanguage": "en",
            "breadcrumb": {"@type": "BreadcrumbList", "itemListElement":
                           breadcrumb_items([("Home", BASE + "/"),
                                             ("Guides", url)])},
        }]

    if ogtype == "article":
        pub, mod = git_dates(fname)
        node = {
            "@type": "TechArticle",
            "headline": title[:110],
            "description": desc,
            "inLanguage": "en",
            "datePublished": pub,
            "dateModified": mod,
            "author": ORG,
            "publisher": ORG,
            "mainEntityOfPage": {"@type": "WebPage", "@id": url},
            "isPartOf": {"@type": "CollectionPage",
                         "@id": BASE + "/guides.html"},
        }
        if image:
            node["image"] = image
        return [
            node,
            {"@type": "BreadcrumbList", "itemListElement": breadcrumb_items([
                ("Home", BASE + "/"),
                ("Guides", BASE + "/guides.html"),
                (title, url)])},
        ]

    return [{"@type": "WebPage", "url": url, "name": title,
             "description": desc, "inLanguage": "en"}]


def render(nodes: list) -> str:
    graph = {"@context": "https://schema.org", "@graph": nodes}
    j = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
    # safe to sit inside <script>: neutralise anything that could close the
    # element or open a comment (a future og:description / FAQ answer could
    # contain "</script>" or "<!--"), plus the two line separators that are
    # valid in JSON but a SyntaxError in a <script> body.
    j = (j.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
         .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    return '%s\n<script type="application/ld+json">\n%s\n</script>\n%s' % (
        START, j, END)


def main() -> None:
    changed, skipped = [], 0
    for path in sorted(ROOT.glob("*.html")):
        fname = path.name
        if fname in SKIP:
            skipped += 1
            continue
        text = path.read_text()
        if "</head>" not in text:
            continue
        nodes = graph_for(fname, text)
        if not nodes:
            continue
        block = render(nodes)
        if START in text:
            updated = BLOCK_RX.sub(lambda _m: block, text, count=1)
        else:
            updated = text.replace("</head>", block + "\n</head>", 1)
        if updated != text:
            path.write_text(updated)
            changed.append(fname)

    if changed:
        print("build_jsonld: updated %d page(s):" % len(changed))
        for f in changed:
            print("  " + f)
    else:
        print("build_jsonld: no changes (%d pages skipped)" % skipped)


if __name__ == "__main__":
    main()
