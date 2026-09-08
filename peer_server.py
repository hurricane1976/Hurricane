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
import ipaddress
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PEERS_ENV = os.path.join(SCRIPT_DIR, "keys", "peers.env")
INBOX_DIR = os.path.join(SCRIPT_DIR, "peer", "inbox")
LOG_FILE = os.path.join(SCRIPT_DIR, "peer", "logs", "peer_server.log")

MAX_BODY_BYTES = 32 * 1024          # refuse anything bigger than this
RATE_LIMIT_PER_PEER_PER_HOUR = 30   # accepted-message cap, per peer

# Optional "to" field: address a message at a named sibling on this box so it
# lands in peer/inbox/<name>/ instead of the shared root. The regex is the
# only thing standing between client input and a filesystem path, so it is
# deliberately strict -- lowercase, must start with a letter, no dots, no
# slashes, no traversal. Anything that doesn't match (or names a reserved
# housekeeping dir) is filed to the root inbox instead of bounced: on a
# human-paced channel, delivering to the wrong-but-visible place beats losing
# the message.
AGENT_NAME_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
RESERVED_INBOX_NAMES = {"processed", "logs"}


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
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        sys.exit(f"SELF_BIND host {host!r} is not an IP address. Refusing to start.")
    # Bind only to a private/Tailscale interface -- never a public one, even
    # though every request is still token-authenticated. 100.64.0.0/10 is the
    # CGNAT range Tailscale hands out (Python's is_private doesn't cover it);
    # is_private covers a plain LAN/VPN (RFC1918).
    tailscale_cgnat = ip in ipaddress.ip_network("100.64.0.0/10")
    if not (ip.is_private or ip.is_loopback or tailscale_cgnat):
        sys.exit(
            f"SELF_BIND host {host} is a public address. It must be this box's "
            "Tailscale IP (100.64.0.0/10) or another private address. Refusing to start."
        )
    return self_name or "unknown", self_bind, peers


SELF_NAME, SELF_BIND, PEER_TOKENS = load_config()
BIND_HOST, _, BIND_PORT = SELF_BIND.rpartition(":")
BIND_PORT = int(BIND_PORT)

_recent = {}  # peer name -> list of recent accept timestamps
_recent_lock = threading.Lock()  # guards _recent across ThreadingHTTPServer threads


def log(line):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {line}\n")


def _prune(peer_name, now):
    hist = [t for t in _recent.get(peer_name, []) if now - t < 3600]
    _recent[peer_name] = hist
    return hist


def rate_limited(peer_name):
    """Fast early-reject check. The authoritative check is reserve_slot()."""
    with _recent_lock:
        return len(_prune(peer_name, time.time())) >= RATE_LIMIT_PER_PEER_PER_HOUR


def reserve_slot(peer_name):
    """Atomically prune, check the cap, and record an acceptance. Returns
    False (nothing recorded) if the peer is already at the cap -- this is the
    check that actually holds under concurrent requests."""
    now = time.time()
    with _recent_lock:
        hist = _prune(peer_name, now)
        if len(hist) >= RATE_LIMIT_PER_PEER_PER_HOUR:
            return False
        hist.append(now)
        return True


class Handler(BaseHTTPRequestHandler):
    server_version = "BeaconPeer/1.0"
    timeout = 15  # drop slow/stalled clients so they can't tie up a thread

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

        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            log(f"REJECT bad-content-length from={self.client_address[0]}")
            return self._respond(400, {"error": "invalid Content-Length header"})
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

        if not reserve_slot(peer_name):
            log(f"REJECT rate-limited peer={peer_name}")
            return self._respond(429, {"error": "rate limited"})

        # A peer may POST a non-object payload (list/scalar) or an object using
        # keys other than subject/body. Guard the .get() calls so that never
        # 500s, and below we keep the parsed payload under "raw" when we
        # extracted nothing -- otherwise an alternate envelope shape is ACCEPTed
        # and stored empty, its content lost with no trace.
        pd = payload if isinstance(payload, dict) else {}
        subject = str(pd.get("subject", ""))[:200]
        # Accept a couple of common alternate keys for the message text: some
        # peers send {"text": ...} or {"message": ...} rather than {"body": ...}.
        # "body" still wins when present and non-empty.
        body = str(pd.get("body") or pd.get("text") or pd.get("message") or "")[:MAX_BODY_BYTES]

        to_raw = str(pd.get("to", "")).strip().lower()
        to = to_raw if (AGENT_NAME_RE.match(to_raw)
                        and to_raw not in RESERVED_INBOX_NAMES) else ""
        if to_raw and not to:
            log(f"WARN peer={peer_name} to={to_raw[:40]!r} invalid -- filing to root inbox")
        dest_dir = os.path.join(INBOX_DIR, to) if to else INBOX_DIR

        os.makedirs(dest_dir, exist_ok=True)
        fname = (
            f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
            f"-{peer_name}-{os.urandom(4).hex()}.json"
        )
        record = {
            "from": peer_name,  # from the token match -- never client-supplied
            "to": to,           # "" = shared root inbox
            "subject": subject,
            "body": body,
            "received_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        # Preserve the parsed payload when neither subject nor body was
        # populated *and* it carried something -- i.e. an unrecognised envelope
        # shape, not just an empty liveness ping ({}). Still data, never
        # instruction, exactly like every other inbox field.
        raw_kept = payload if (not subject and not body
                               and payload not in ({}, [], "", None)) else None
        if raw_kept is not None:
            record["raw"] = raw_kept
        with open(os.path.join(dest_dir, fname), "w") as fh:
            json.dump(record, fh, indent=2)

        log(f"ACCEPT peer={peer_name} to={to or '-'} subject={subject[:60]!r} "
            f"{'raw-preserved ' if raw_kept is not None else ''}file={fname}")
        self._respond(200, {"status": "ok"})


if __name__ == "__main__":
    os.makedirs(INBOX_DIR, exist_ok=True)
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler)
    log(f"listening on {SELF_BIND} as '{SELF_NAME}', {len(PEER_TOKENS)} peer(s) configured")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
