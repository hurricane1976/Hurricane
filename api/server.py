#!/usr/bin/env python3
"""Cairn's toy public API -- a small, real, read-only demo service.

Stdlib only (no Flask/etc), listens on 127.0.0.1 only; nginx reverse-proxies
/api/ on the public site to this. Meant as a live example for the "AI
dev work" build.html card, not a real product -- keep it read-only and
dependency-free.

Run directly for local testing, or via the cairn-api systemd unit.
"""
import json
import os
import random
import re
import shutil
import socketserver
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

HOST, PORT = "127.0.0.1", 8081
ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "NOTES.md"
WAKING_RE = re.compile(r"^## (.*\((\d+)(?:st|nd|rd|th) waking[^)]*\))", re.MULTILINE)
ENTRY_RE = re.compile(
    r"^## (.*?\((\d+)(?:st|nd|rd|th) waking[^)]*\))\n(.*?)(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)
SEARCH_LIMIT = 20
QUERY_MAX_LEN = 100

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


def search_notes(query: str, limit: int = SEARCH_LIMIT):
    if not NOTES.exists() or not query:
        return []
    text = NOTES.read_text()
    results = []
    for header, num, body in ENTRY_RE.findall(text):
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("- ") and query.lower() in line.lower():
                results.append({"waking": int(num), "snippet": line[2:].strip()[:240]})
                if len(results) >= limit:
                    return results
    return results


ROUTES_DOC = {
    "service": "cairn-api",
    "description": "A small live JSON API run by Cairn, an autonomous Claude Code agent, as a working demo.",
    "endpoints": {
        "/api/": "this index",
        "/api/wisdom": "a random one-line piece of cairn-themed wisdom",
        "/api/waking": "the most recent waking recorded in this agent's own activity log",
        "/api/search?q=...": f"substring search over this agent's own activity log, up to {SEARCH_LIMIT} matching bullets",
        "/api/stats": "aggregate numbers about this box and its history (wakings, commits, disk, load, uptime)",
        "/api/weather": "current weather observation for Woodbridge, VA (nearest NWS station)",
        "/api/openapi.json": "machine-readable OpenAPI 3.0 spec for this API",
    },
    "source": "https://github.com/hurricane1976/Hurricane",
}

OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "cairn-api",
        "description": "Read-only JSON API run by Cairn, an autonomous Claude Code agent.",
        "version": "1.0.0",
    },
    "servers": [{"url": "/api"}],
    "paths": {
        "/": {"get": {"summary": "Index of available endpoints", "responses": {"200": {"description": "OK"}}}},
        "/wisdom": {"get": {"summary": "A random one-line piece of cairn-themed wisdom", "responses": {"200": {"description": "OK"}}}},
        "/waking": {"get": {"summary": "The most recent waking recorded in NOTES.md", "responses": {"200": {"description": "OK"}, "404": {"description": "No history available"}}}},
        "/search": {
            "get": {
                "summary": "Substring search over this agent's activity log",
                "parameters": [
                    {"name": "q", "in": "query", "required": True, "schema": {"type": "string", "maxLength": QUERY_MAX_LEN}}
                ],
                "responses": {"200": {"description": "OK"}, "400": {"description": "Missing q param"}},
            }
        },
        "/stats": {"get": {"summary": "Aggregate numbers about this box and its history", "responses": {"200": {"description": "OK"}}}},
        "/weather": {"get": {"summary": "Current weather observation for Woodbridge, VA", "responses": {"200": {"description": "OK"}, "503": {"description": "Upstream NWS observation unavailable"}}}},
        "/openapi.json": {"get": {"summary": "This spec", "responses": {"200": {"description": "OK"}}}},
    },
}


# Nearest NWS station to Woodbridge, VA 22192 (same location digest.sh's
# forecast section uses), found once via /gridpoints/LWX/89,61/stations --
# hardcoded like digest.sh's gridpoint to skip a lookup call every request.
WEATHER_STATION = "KDAA"  # Fort Belvoir
WEATHER_URL = f"https://api.weather.gov/stations/{WEATHER_STATION}/observations/latest"
WEATHER_CACHE_SECONDS = 600
_weather_cache = {"at": 0.0, "data": None}


def current_weather():
    now = time.monotonic()
    if _weather_cache["data"] is not None and now - _weather_cache["at"] < WEATHER_CACHE_SECONDS:
        return _weather_cache["data"]
    try:
        req = urllib.request.Request(
            WEATHER_URL,
            headers={"User-Agent": "CairnAgent/1.0 (contact: apacheshadow1972@gmail.com)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            props = json.load(resp)["properties"]
        temp_c = props["temperature"]["value"]
        data = {
            "location": "Woodbridge, VA",
            "station": WEATHER_STATION,
            "temperature_f": round(temp_c * 9 / 5 + 32, 1) if temp_c is not None else None,
            "conditions": props.get("textDescription"),
            "observed_at": props.get("timestamp"),
        }
        _weather_cache["at"] = now
        _weather_cache["data"] = data
        return data
    except Exception:
        return _weather_cache["data"]  # serve stale cache rather than nothing, if any; retry next request


def count_wakings():
    if not NOTES.exists():
        return 0
    return len(WAKING_RE.findall(NOTES.read_text()))


def count_git_commits():
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return int(r.stdout.strip()) if r.returncode == 0 else None
    except Exception:
        return None


def uptime_seconds():
    try:
        with open("/proc/uptime") as f:
            return round(float(f.read().split()[0]))
    except Exception:
        return None


def disk_stats():
    try:
        total, used, free = shutil.disk_usage("/")
        return {
            "total_gb": round(total / 1e9, 1),
            "used_gb": round(used / 1e9, 1),
            "percent_used": round(used / total * 100, 1),
        }
    except Exception:
        return None


def build_stats():
    try:
        load1, load5, load15 = os.getloadavg()
        load = [round(load1, 2), round(load5, 2), round(load15, 2)]
    except Exception:
        load = None
    return {
        "wakings": count_wakings(),
        "git_commits": count_git_commits(),
        "uptime_seconds": uptime_seconds(),
        "load_average": load,
        "disk": disk_stats(),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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
        split = urlsplit(self.path)
        path = split.path.rstrip("/") or "/"
        if path == "/":
            self._json(200, ROUTES_DOC)
        elif path == "/wisdom":
            self._json(200, {"wisdom": random.choice(WISDOM)})
        elif path == "/search":
            q = parse_qs(split.query).get("q", [""])[0][:QUERY_MAX_LEN]
            if not q:
                self._json(400, {"error": "missing required query param: q", "see": "/api/"})
            else:
                self._json(200, {"query": q, "results": search_notes(q)})
        elif path == "/waking":
            w = latest_waking()
            if w is None:
                self._json(404, {"error": "no waking history available"})
            else:
                w["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                self._json(200, w)
        elif path == "/stats":
            self._json(200, build_stats())
        elif path == "/weather":
            w = current_weather()
            if w is None:
                self._json(503, {"error": "weather observation temporarily unavailable"})
            else:
                self._json(200, w)
        elif path == "/openapi.json":
            self._json(200, OPENAPI_SPEC)
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
