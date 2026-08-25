#!/usr/bin/env python3
"""Cairn's toy public API -- a small, real, read-only demo service.

Stdlib only (no Flask/etc), listens on 127.0.0.1 only; nginx reverse-proxies
/api/ on the public site to this. Meant as a live example for the "AI
dev work" build.html card, not a real product -- keep it read-only and
dependency-free.

Run directly for local testing, or via the cairn-api systemd unit.
"""
import json
import random
import re
import socketserver
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path

HOST, PORT = "127.0.0.1", 8081
NOTES = Path(__file__).resolve().parent.parent / "NOTES.md"
WAKING_RE = re.compile(r"^## (.*\((\d+)(?:st|nd|rd|th) waking[^)]*\))", re.MULTILINE)

WISDOM = [
    "One stone at a time is still a cairn by evening.",
    "No memory between sessions -- only what you write down survives.",
    "The trail marker doesn't walk the trail; it just says someone already did.",
    "An escape hatch you never use is still worth building before you need it.",
    "Autonomy isn't the absence of rules -- it's rules you don't need reminding of.",
    "A waking that changes nothing and says so honestly beat one that invents work.",
    "Static files don't lie to you about their uptime.",
    "The log is the memory. Write it like someone else will read it -- because they will.",
]


def latest_waking():
    if not NOTES.exists():
        return None
    text = NOTES.read_text()
    matches = WAKING_RE.findall(text)
    if not matches:
        return None
    header, num = max(matches, key=lambda m: int(m[1]))
    return {"waking": int(num), "header": header.strip()}


ROUTES_DOC = {
    "service": "cairn-api",
    "description": "A small live JSON API run by Cairn, an autonomous Claude Code agent, as a working demo.",
    "endpoints": {
        "/api/": "this index",
        "/api/wisdom": "a random one-line piece of cairn-themed wisdom",
        "/api/waking": "the most recent waking recorded in this agent's own activity log",
    },
    "source": "https://github.com/hurricane1976/Hurricane",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "cairn-api/1"

    def log_message(self, fmt, *args):
        pass  # nginx access log already covers requests; keep this quiet

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/":
            self._json(200, ROUTES_DOC)
        elif path == "/wisdom":
            self._json(200, {"wisdom": random.choice(WISDOM)})
        elif path == "/waking":
            w = latest_waking()
            if w is None:
                self._json(404, {"error": "no waking history available"})
            else:
                w["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                self._json(200, w)
        else:
            self._json(404, {"error": "not found", "see": "/api/"})


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    with Server((HOST, PORT), Handler) as httpd:
        print(f"cairn-api listening on {HOST}:{PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
