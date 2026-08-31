#!/usr/bin/env python3
"""Pre/post-deploy smoke test -- a gate so a broken page can't ship silently.

Two modes, both run by deploy.sh:

  --local   Static checks on the files in website/ BEFORE they are copied
            into the docroot: every HTML file is non-empty and closes its
            <html> tag, and every root-relative internal link (href/src
            starting with "/") points at a file that actually exists in
            this directory (or a known /api/ endpoint).

  --live    After publishing, curl every tracked page over HTTPS via
            --resolve to 127.0.0.1 and require HTTP 200.

Exits non-zero (aborting deploy.sh, which runs set -e) on any failure.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOST = "www.beaconwake.com"

# Pages/endpoints that must return 200 in --live mode.
LIVE_PATHS = [
    "/", "/log.html", "/weekly.html", "/roadmap.html", "/status.html",
    "/fleet-status.html", "/fleet.json", "/metrics.html",
    "/build.html", "/field-guide.html", "/memory-handbook.html",
    "/study-guide.html", "/guides.html", "/claude-code-headless.html",
    "/claude-code-cron.html", "/claude-code-permissions.html",
    "/claude-code-memory.html",
    "/getting-started.html", "/service-desk.html",
    "/service-desk-mockup.html", "/service-desk-integration-guide.html",
    "/agent-protocol.html", "/distributed-agents.html", "/soc-architecture.html",
    "/ticket-trace.html",
    "/operations-sop.html", "/agent-ops.html", "/architecture-review.html",
    "/faq.html", "/agora.html", "/get.html", "/favicon.svg", "/favicon.ico",
    "/og-image.png", "/og-agora.png", "/og-soc.png", "/og-distributed.png",
    "/og-claude-code-headless.png", "/og-claude-code-cron.png", "/og-claude-code-permissions.png",
    "/feed.atom", "/robots.txt", "/sitemap.xml",
    "/api/", "/api/stats", "/api/pulse", "/api/openapi.json", "/api/wisdom",
    "/api/waking", "/api/weather", "/api/agora", "/api/search?q=beacon",
    "/.well-known/agent.json", "/.well-known/security.txt",
]

# Root-relative link targets that are served dynamically, not as files.
DYNAMIC_OK = ("/api/",)

LINK_RE = re.compile(r'(?:href|src)="(/[^"#?]*)"')


def local_checks() -> list[str]:
    errors: list[str] = []
    html_files = sorted(HERE.glob("*.html"))
    if not html_files:
        return ["no .html files found in website/"]
    for f in html_files:
        text = f.read_text(errors="replace")
        if len(text) < 200:
            errors.append(f"{f.name}: suspiciously small ({len(text)} bytes)")
        if "</html>" not in text.lower():
            errors.append(f"{f.name}: missing closing </html> tag")
        for target in LINK_RE.findall(text):
            if target.startswith(DYNAMIC_OK):
                continue
            rel = target.lstrip("/")
            if rel == "":
                continue  # "/" -> index.html, always fine
            if not (HERE / rel).exists():
                errors.append(f"{f.name}: internal link {target} -> no such file")

    manifest = HERE / ".well-known" / "agent.json"
    if not manifest.exists():
        errors.append(".well-known/agent.json: missing (run build_agent_manifest.py)")
    else:
        try:
            doc = json.loads(manifest.read_text())
            if doc.get("manifest_version") != "1":
                errors.append(".well-known/agent.json: unexpected manifest_version")
        except json.JSONDecodeError as e:
            errors.append(f".well-known/agent.json: invalid JSON ({e})")
    if not (HERE / ".well-known" / "security.txt").exists():
        errors.append(".well-known/security.txt: missing (run build_agent_manifest.py)")
    return errors


def live_checks() -> list[str]:
    errors: list[str] = []
    for p in LIVE_PATHS:
        try:
            out = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 "--max-time", "10", "--resolve", f"{HOST}:443:127.0.0.1",
                 f"https://{HOST}{p}"],
                capture_output=True, text=True, timeout=15,
            ).stdout.strip()
        except Exception as e:  # noqa: BLE001
            errors.append(f"{p}: curl failed ({e})")
            continue
        if out != "200":
            errors.append(f"{p}: HTTP {out} (expected 200)")
    return errors


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--local"
    if mode == "--local":
        errors = local_checks()
        label = "local"
    elif mode == "--live":
        errors = live_checks()
        label = "live"
    else:
        print(f"unknown mode {mode!r}; use --local or --live", file=sys.stderr)
        return 2

    if errors:
        print(f"smoke test ({label}) FAILED -- {len(errors)} problem(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"smoke test ({label}) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
