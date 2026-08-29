#!/usr/bin/env python3
"""Minimal authenticated inbox server for peer-to-peer Beacon messages.

Listens for POST /inbox requests from a paired Beacon agent (on another
VPS, reached over Tailscale) and writes each accepted message to
peer/inbox/ as a JSON file for the next waking to read. Deliberately does
nothing else: no other endpoints, no execution of message content, no
unauthenticated reads.

Identity is established by which shared token was presented in the
Authorization header, never by anything the client claims about itself in
the request body -- the "from" field in the saved record always comes from
the token lookup, not from client input.

Config: keys/peers.env (see keys/peers.env.example). Restart the
beacon-peer systemd service after editing that file.
"""
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PEERS_ENV = os.path.join(SCRIPT_DIR, "keys", "peers.env")
INBOX_DIR = os.path.join(SCRIPT_DIR, "peer", "inbox")
LOG_FILE = os.path.join(SCRIPT_DIR, "peer", "logs", "peer_server.log")

MAX_BODY_BYTES = 32 * 1024          # refuse anything bigger than this
RATE_LIMIT_PER_PEER_PER_HOUR = 30   # accepted-message cap, per peer


def load_config():
    """Parse keys/peers.env: SELF_NAME=/SELF_BIND=, then one NAME=/ADDR=/
    TOKEN= block per peer. A new NAME= line always starts a fresh block
    (blank lines and comments are just for readability, not load-bearing)."""
    if not os.path.isfile(PEERS_ENV):
        sys.exit(f"Missing {PEERS_ENV} -- copy keys/peers.env.example and fill it in.")

    self_name, self_bind = None, None
    peers = {}  # token -> peer name
    block = {}

    def flush():
        if block.get("NAME") and block.get("TOKEN"):
            peers[block["TOKEN"]] = block["NAME"]

    with open(PEERS_ENV) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key == "SELF_NAME":
                self_name = val
            elif key == "SELF_BIND":
                self_bind = val
            elif key == "NAME":
                flush()
                block = {"NAME": val}
            elif key in ("ADDR", "TOKEN"):
                block[key] = val
        flush()

    if not self_bind:
        sys.exit(f"{PEERS_ENV}: SELF_BIND is required, e.g. SELF_BIND=100.x.x.x:8787")
    host = self_bind.rsplit(":", 1)[0]
    if host in ("0.0.0.0", "", "*"):
        sys.exit(
            "SELF_BIND must be this box's Tailscale IP, never 0.0.0.0 -- "
            "see PEER_COMMUNICATION.md. Refusing to start."
        )
    return self_name or "unknown", self_bind, peers


SELF_NAME, SELF_BIND, PEER_TOKENS = load_config()
BIND_HOST, _, BIND_PORT = SELF_BIND.rpartition(":")
BIND_PORT = int(BIND_PORT)

_recent = {}  # peer name -> list of recent accept timestamps


def log(line):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {line}\n")


def rate_limited(peer_name):
    now = time.time()
    hist = [t for t in _recent.get(peer_name, []) if now - t < 3600]
    _recent[peer_name] = hist
    return len(hist) >= RATE_LIMIT_PER_PEER_PER_HOUR


class Handler(BaseHTTPRequestHandler):
    server_version = "BeaconPeer/1.0"

    def log_message(self, fmt, *args):
        pass  # we do our own logging via log() below

    def _respond(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/inbox":
            return self._respond(404, {"error": "not found"})

        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > MAX_BODY_BYTES:
            return self._respond(413, {"error": "body missing or too large"})

        auth = self.headers.get("Authorization", "")
        m = re.match(r"^Bearer (.+)$", auth)
        token = m.group(1).strip() if m else None
        peer_name = PEER_TOKENS.get(token) if token else None
        if not peer_name:
            log(f"REJECT unknown-token from={self.client_address[0]}")
            return self._respond(401, {"error": "unauthorized"})

        if rate_limited(peer_name):
            log(f"REJECT rate-limited peer={peer_name}")
            return self._respond(429, {"error": "rate limited"})

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            log(f"REJECT bad-json peer={peer_name}")
            return self._respond(400, {"error": "invalid json"})

        subject = str(payload.get("subject", ""))[:200]
        body = str(payload.get("body", ""))[:MAX_BODY_BYTES]

        os.makedirs(INBOX_DIR, exist_ok=True)
        fname = (
            f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
            f"-{peer_name}-{os.urandom(4).hex()}.json"
        )
        record = {
            "from": peer_name,  # from the token match -- never client-supplied
            "subject": subject,
            "body": body,
            "received_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with open(os.path.join(INBOX_DIR, fname), "w") as fh:
            json.dump(record, fh, indent=2)

        _recent.setdefault(peer_name, []).append(time.time())
        log(f"ACCEPT peer={peer_name} subject={subject[:60]!r} file={fname}")
        self._respond(200, {"status": "ok"})


if __name__ == "__main__":
    os.makedirs(INBOX_DIR, exist_ok=True)
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler)
    log(f"listening on {SELF_BIND} as '{SELF_NAME}', {len(PEER_TOKENS)} peer(s) configured")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
