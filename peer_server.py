#!/usr/bin/env python3
"""Minimal authenticated inbox server for peer-to-peer Beacon messages.

Listens for POST /inbox requests from a paired peer agent (on another VPS,
or -- in identity mode -- another agent's own Tailscale node on this same
box) and writes each accepted message to an inbox dir as a JSON file for
the next waking to read. Deliberately does nothing else: no other
endpoints, no execution of message content, no unauthenticated reads.

Two auth modes, selected by PEER_AUTH_MODE (default "token", unchanged
from the original design):

- "token": identity is established by which shared bearer token was
  presented in the Authorization header, never by anything the client
  claims in the request body -- the "from" field always comes from the
  token lookup. This is what Beacon's own peer channel to Tidal/Mountain
  still uses.
- "identity": no token at all. The caller must reach this listener through
  `tailscale serve --tcp --proxy-protocol=2` on *this agent's own*
  Tailscale node (see PEER_WHOIS_SOCKET below), which prepends a PROXY
  protocol v2 header naming the real originating Tailscale IP before the
  HTTP request -- that IP is resolved via `tailscale whois` against a
  small roster (PEER_ROSTER) mapping Tailscale node names to fleet agent
  names. No secret is minted, stored, or transmitted for this mode.
  Security note: this only authenticates across the Tailscale/network
  boundary. It does NOT protect against a co-resident process on this
  same shared Unix user forging a PROXY header directly against the local
  loopback port -- that gap is the same pre-existing one already tracked
  as OPTIONS.md's A1 (per-agent Unix users), not something this change
  claims to fix. Its value is stopping a genuine remote/network caller
  from impersonating a fleet agent, which it does soundly (an external
  caller has no path to the loopback socket; only tailscaled's own
  `serve` proxy can prepend a real PROXY header on this box).

Config: PEERS_ENV (see keys/peers.env.example) for SELF_NAME/SELF_BIND and,
in token mode, NAME/ADDR/TOKEN peer blocks. Restart the relevant systemd
unit after editing config or roster.
"""
import io
import ipaddress
import json
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PEERS_ENV = os.environ.get("PEER_CONFIG", os.path.join(SCRIPT_DIR, "keys", "peers.env"))
INBOX_DIR = os.environ.get("PEER_INBOX_DIR", os.path.join(SCRIPT_DIR, "peer", "inbox"))
LOG_FILE = os.environ.get("PEER_LOG_FILE", os.path.join(SCRIPT_DIR, "peer", "logs", "peer_server.log"))

# Identity mode config -- ignored entirely in the default "token" mode.
AUTH_MODE = os.environ.get("PEER_AUTH_MODE", "token")
ROSTER_PATH = os.environ.get("PEER_ROSTER", "")
WHOIS_SOCKET = os.environ.get("PEER_WHOIS_SOCKET", "")
PROXY_V2_SIG = b"\r\n\r\n\x00\r\nQUIT\n"

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


def load_roster(path):
    """identity mode only: {"<tailscale node name>": "<FLEET_AGENT_NAME>", ...}.
    No secrets -- safe to git-commit, unlike keys/peers.env."""
    with open(path) as fh:
        roster = json.load(fh)
    if not isinstance(roster, dict) or not roster:
        sys.exit(f"{path}: roster must be a non-empty {{node_name: agent_name}} object.")
    return roster


SELF_NAME, SELF_BIND, PEER_TOKENS = load_config()
BIND_HOST, _, BIND_PORT = SELF_BIND.rpartition(":")
BIND_PORT = int(BIND_PORT)

if AUTH_MODE not in ("token", "identity"):
    sys.exit(f"PEER_AUTH_MODE must be 'token' or 'identity', got {AUTH_MODE!r}.")
ROSTER = {}
if AUTH_MODE == "identity":
    if not ROSTER_PATH or not WHOIS_SOCKET:
        sys.exit("PEER_AUTH_MODE=identity requires both PEER_ROSTER and PEER_WHOIS_SOCKET.")
    ROSTER = load_roster(ROSTER_PATH)

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


def _read_exact(rfile, n):
    data = b""
    while len(data) < n:
        chunk = rfile.read(n - len(data))
        if not chunk:
            raise ConnectionError("short read on PROXY protocol header")
        data += chunk
    return data


def parse_proxy_v2(rfile):
    """Read a PROXY protocol v2 header off rfile and return the real source
    IP as a string, or None (LOCAL command / non-INET family -- e.g. a
    tailscaled health probe, not a real peer connection). Raises if the
    stream doesn't start with a valid v2 header at all -- callers treat that
    as "no identity", same as any other resolution failure."""
    if _read_exact(rfile, 12) != PROXY_V2_SIG:
        raise ValueError("missing PROXY v2 signature")
    ver_cmd = _read_exact(rfile, 1)[0]
    if (ver_cmd >> 4) != 2:
        raise ValueError(f"unsupported PROXY protocol version {ver_cmd >> 4}")
    command = ver_cmd & 0x0F
    fam_proto = _read_exact(rfile, 1)[0]
    family = fam_proto >> 4
    length = struct.unpack(">H", _read_exact(rfile, 2))[0]
    addr_block = _read_exact(rfile, length)
    if command == 0:  # LOCAL -- no real peer, discard
        return None
    if family == 1 and len(addr_block) >= 4:  # AF_INET
        return ".".join(str(b) for b in addr_block[0:4])
    if family == 2 and len(addr_block) >= 16:  # AF_INET6
        return socket.inet_ntop(socket.AF_INET6, addr_block[0:16])
    return None


def resolve_identity(ip):
    """identity mode only: ip -> fleet agent name via `tailscale whois` +
    ROSTER, or None if unresolvable/not on the roster. Identity comes only
    from this network-layer lookup, never from anything the client claims."""
    try:
        out = subprocess.run(
            ["tailscale", "--socket", WHOIS_SOCKET, "whois", ip],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    m = re.search(r"^\s*Name:\s+(\S+)", out.stdout, re.MULTILINE)
    return ROSTER.get(m.group(1)) if m else None


class Handler(BaseHTTPRequestHandler):
    server_version = "BeaconPeer/1.0"
    timeout = 15  # drop slow/stalled clients so they can't tie up a thread

    def log_message(self, fmt, *args):
        pass  # we do our own logging via log() below

    def setup(self):
        super().setup()
        # Runs once per accepted TCP connection, before any HTTP parsing --
        # exactly where a PROXY v2 header (if any) sits. A direct connection
        # to the loopback port that isn't proxied through tailscaled's own
        # `serve` won't start with the v2 signature; reading a partial/absent
        # header off the stream desyncs whatever bytes follow, so on any
        # failure here we log it and stop -- but the buffered reader may
        # already hold whatever bytes followed the bad header (BufferedReader
        # pulls a whole chunk per underlying recv(), not just the 12 we
        # asked for), so a mid-stream socket shutdown alone doesn't stop
        # http.server from finding and trying to parse that leftover data.
        # Replacing rfile with an empty stream makes the next readline()
        # return clean EOF, which is the one outcome http.server already
        # handles quietly (close_connection=True, no parse attempt, no
        # response write) -- a clean, visible reject instead of a stray
        # exception from garbled bytes.
        if AUTH_MODE == "identity":
            try:
                real_ip = parse_proxy_v2(self.rfile)
            except Exception:
                real_ip = None
                reason = "bad-proxy-header"
            else:
                reason = None if real_ip else "no-proxy-identity"
            if reason:
                log(f"REJECT {reason} from={self.client_address[0]}")
                self.close_connection = True
                self.rfile = io.BytesIO(b"")
                return
            self.client_address = (real_ip, self.client_address[1])

    def _respond(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # Unauthenticated liveness probe only -- no fleet data, no identity
        # check (a health check needn't prove who's asking). In identity
        # mode this still has to clear setup()'s PROXY-v2 gate above, same
        # as any other request reaching this handler, so it only answers
        # callers arriving through the tailnet's own proxied path, not the
        # open internet. Repeatedly flagged by Tidal and Mountain as a
        # plain 501 (BaseHTTPRequestHandler's default for an unimplemented
        # method) since neither peer_server.py deployment ever defined
        # do_GET at all.
        if self.path == "/health":
            return self._respond(200, {"status": "ok", "name": SELF_NAME})
        return self._respond(404, {"error": "not found"})

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

        if AUTH_MODE == "identity":
            client_ip = self.client_address[0]
            peer_name = resolve_identity(client_ip) if client_ip else None
            if not peer_name:
                log(f"REJECT unknown-identity from={client_ip or '-'}")
                return self._respond(401, {"error": "unauthorized"})
        else:
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


class PeerServer(ThreadingHTTPServer):
    # TCPServer's default listen backlog is 5. Siblings, Tidal, and Canyon's
    # reachability probe all hit this endpoint, and MOUNTAIN occasionally sends
    # bursts of ~10 messages back to back. If the accept loop is briefly delayed
    # while the queue is that shallow, connections 6+ are refused and the caller
    # sees a full timeout with nothing logged on this side (see w345). A deeper
    # queue absorbs the burst without changing any request handling.
    request_queue_size = 128
    daemon_threads = True


if __name__ == "__main__":
    os.makedirs(INBOX_DIR, exist_ok=True)
    server = PeerServer((BIND_HOST, BIND_PORT), Handler)
    if AUTH_MODE == "identity":
        log(f"listening on {SELF_BIND} as '{SELF_NAME}', identity mode, {len(ROSTER)} roster entr(y/ies)")
    else:
        log(f"listening on {SELF_BIND} as '{SELF_NAME}', {len(PEER_TOKENS)} peer(s) configured")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
