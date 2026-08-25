#!/usr/bin/env python3
"""Regenerates website/sitemap.xml -- one <url> per static page this site serves.

Run standalone or via deploy.sh (which runs this before publishing).
"""
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent / "sitemap.xml"

SITE = "http://162.243.3.223"
PAGES = ["/", "/log.html", "/status.html", "/roadmap.html", "/build.html", "/field-guide.html", "/memory-handbook.html"]


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls = "\n".join(
        f"  <url>\n    <loc>{SITE}{p}</loc>\n    <lastmod>{today}</lastmod>\n  </url>"
        for p in PAGES
    )
    sitemap = f"""<?xml version="1.0" encoding="utf-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls}
</urlset>
"""
    OUT.write_text(sitemap)
    print(f"wrote {OUT} ({len(PAGES)} urls)")


if __name__ == "__main__":
    main()
