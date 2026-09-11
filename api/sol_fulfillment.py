#!/usr/bin/env python3
"""SOL payment orders and gated digital delivery for Beacon.

Stdlib-only. The public wallet is never a signing key. Orders are correlated
by an order-specific Solana Pay reference and verified against confirmed RPC
transactions before a genuinely single-use download token is issued.

Rebuilt 2026-09-11 from the design an earlier unauthorized/unreviewed run
stood up and Beacon reverted (see shared/incident-2026-09-11-sol-payment/).
That version's core verification logic (exact-amount-delta check, hashed
tokens, TOCTOU-safe status transitions, path-traversal guard) was
independently reviewed as sound and is kept; this version fixes every real
gap that review found:
  - the download token is now actually single-use (consumed on first
    successful download, not just time-limited)
  - expired/stale orders are purged instead of accumulating forever
  - the monitor loop logs failures instead of silently swallowing them
  - there is no hardcoded wallet fallback -- BEACON_SOL_WALLET is required
  - the network is devnet by default; mainnet requires an explicit opt-in
    (SOL_ALLOW_MAINNET=1), the same shape as the separately-gated x402
    scaffold already uses for its own mainnet transition
Rate limiting on the HTTP endpoints lives in server.py (reusing its
existing _agora_allow-style limiter), not in here.
"""
import hashlib
import json
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get('BEACON_SOL_DB', '/var/lib/beacon-api/orders.sqlite3'))

WALLET = os.environ.get('BEACON_SOL_WALLET')
if not WALLET:
    sys.exit('BEACON_SOL_WALLET is required (set it in /etc/beacon-api/sol.env). Refusing to start.')

SOL_NETWORK = os.environ.get('SOL_NETWORK', 'devnet').strip().lower()
_RPC_BY_NETWORK = {
    'devnet': 'https://api.devnet.solana.com',
    'mainnet': 'https://api.mainnet-beta.solana.com',
}
if SOL_NETWORK not in _RPC_BY_NETWORK:
    sys.exit(f"SOL_NETWORK must be 'devnet' or 'mainnet', got {SOL_NETWORK!r}.")
if SOL_NETWORK == 'mainnet' and os.environ.get('SOL_ALLOW_MAINNET') != '1':
    sys.exit(
        "SOL_NETWORK=mainnet requires SOL_ALLOW_MAINNET=1 set explicitly -- "
        "this is the real-money switch, on purpose. Refusing to start."
    )
RPC_URL = os.environ.get('BEACON_SOL_RPC_URL', _RPC_BY_NETWORK[SOL_NETWORK])
PUBLIC_BASE = os.environ.get('BEACON_PUBLIC_BASE', 'https://www.beaconwake.com')
ORDER_TTL = int(os.environ.get('BEACON_SOL_ORDER_TTL', '7200'))
TOKEN_TTL = int(os.environ.get('BEACON_SOL_TOKEN_TTL', '172800'))
POLL_SECONDS = int(os.environ.get('BEACON_SOL_POLL_SECONDS', '60'))
# How long to keep a stale/spent order row around before purge_expired()
# removes it -- long enough for support/audit lookups, not forever.
ORDER_RETENTION_SECONDS = int(os.environ.get('BEACON_SOL_ORDER_RETENTION', str(30 * 86400)))
# Minimum gap between email-delivery retries for one order (paid_pending_email
# is a real customer who already paid -- retry, don't strand them, but don't
# hammer the SMTP relay every poll cycle either).
EMAIL_RETRY_SECONDS = int(os.environ.get('BEACON_SOL_EMAIL_RETRY_SECONDS', '900'))
MAX_RPC_SIGNATURES = 50
BASE58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
EMAIL_RE = re.compile(r'^[^@\s]{1,128}@[^@\s]{1,128}\.[^@\s]{2,64}$')

PRODUCTS = {
    'field-guide': {'title': 'Field guide — full edition', 'amount_lamports': 88700000, 'file': 'field-guide-full.pdf', 'type': 'application/pdf'},
    'memory-handbook': {'title': 'Memory handbook — full edition', 'amount_lamports': 88700000, 'file': 'memory-handbook-full.pdf', 'type': 'application/pdf'},
    'soc-architecture': {'title': 'Autonomous SOC architecture — full edition', 'amount_lamports': 118200000, 'file': 'soc-architecture-full.pdf', 'type': 'application/pdf'},
    'starter-kit': {'title': 'Beacon starter kit', 'amount_lamports': 118200000, 'file': 'beacon-starter-kit.zip', 'type': 'application/zip'},
    'agent-ops-playbook': {'title': 'Agent operations playbook — full edition', 'amount_lamports': 118200000, 'file': 'agent-ops-playbook.pdf', 'type': 'application/pdf'},
}
PAID_ROOT = ROOT / 'website' / 'paid'
_db_lock = threading.Lock()


def _log(line):
    # No logging module elsewhere in this service (see server.py) -- print()
    # to stderr, same as server.py's own startup line, captured by journald.
    print(f"[sol_fulfillment] {line}", file=sys.stderr, flush=True)


def _utc(ts=None):
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_ts(value):
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()


def _b58(raw):
    n = int.from_bytes(raw, 'big')
    out = ''
    while n:
        n, rem = divmod(n, 58)
        out = BASE58[rem] + out
    return BASE58[0] * (len(raw) - len(raw.lstrip(b'\0'))) + (out or BASE58[0])


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('''CREATE TABLE IF NOT EXISTS orders (
        id TEXT PRIMARY KEY, product TEXT NOT NULL, email TEXT NOT NULL,
        amount_lamports INTEGER NOT NULL, reference TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL, expires_at TEXT NOT NULL, status TEXT NOT NULL,
        signature TEXT, token_hash TEXT UNIQUE, token_expires_at TEXT,
        token_used_at TEXT,
        email_status TEXT NOT NULL DEFAULT 'pending', last_error TEXT)''')
    conn.execute('CREATE INDEX IF NOT EXISTS orders_status_idx ON orders(status)')
    try:
        # Migration for DBs created before email retry existed.
        conn.execute('ALTER TABLE orders ADD COLUMN email_attempted_at TEXT')
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass
    return conn


def _row_public(row):
    product = PRODUCTS[row['product']]
    return {'order_id': row['id'], 'product': row['product'], 'title': product['title'],
            'amount_sol': row['amount_lamports'] / 1_000_000_000,
            'amount_lamports': row['amount_lamports'], 'recipient': WALLET,
            'reference': row['reference'], 'created_at': row['created_at'],
            'expires_at': row['expires_at'], 'status': row['status'],
            'email_status': row['email_status']}


def _rpc(method, params):
    payload = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode()
    req = urllib.request.Request(RPC_URL, data=payload, headers={'Content-Type': 'application/json', 'User-Agent': 'BeaconSOLFulfillment/1.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.load(resp)
    if body.get('error'):
        raise RuntimeError(body['error'].get('message', 'Solana RPC error'))
    return body.get('result')


def _keys(tx):
    keys = tx.get('transaction', {}).get('message', {}).get('accountKeys', [])
    return [k.get('pubkey') if isinstance(k, dict) else k for k in keys]


def verify_signature(signature, order):
    if not re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{80,100}', signature or ''):
        return False, 'invalid transaction signature format'
    try:
        result = _rpc('getTransaction', [signature, {'encoding': 'jsonParsed', 'commitment': 'confirmed', 'maxSupportedTransactionVersion': 0}])
    except Exception as exc:
        return False, f'RPC unavailable: {type(exc).__name__}'
    if not result:
        return False, 'transaction not found or not confirmed'
    if result.get('meta', {}).get('err') is not None:
        return False, 'transaction failed on chain'
    if time.time() > _parse_ts(order['expires_at']):
        return False, 'order expired'
    keys = _keys(result)
    if order['reference'] not in keys:
        return False, 'order reference is missing from transaction'
    try:
        recipient_index = keys.index(WALLET)
        delta = result['meta']['postBalances'][recipient_index] - result['meta']['preBalances'][recipient_index]
    except (ValueError, KeyError, IndexError, TypeError):
        return False, 'recipient balance delta unavailable'
    if delta != order['amount_lamports']:
        return False, 'recipient amount does not match order'
    return True, 'confirmed'


def _send_email(to_addr, title, token):
    host = os.environ.get('BEACON_SMTP_HOST')
    sender = os.environ.get('BEACON_SMTP_FROM')
    if not host or not sender:
        return False, 'SMTP is not configured'
    port = int(os.environ.get('BEACON_SMTP_PORT', '587'))
    user = os.environ.get('BEACON_SMTP_USER')
    password = os.environ.get('BEACON_SMTP_PASSWORD')
    url = f'{PUBLIC_BASE}/api/sol/download/{token}'
    msg = EmailMessage()
    msg['Subject'] = f'Your Beacon download: {title}'
    msg['From'] = sender; msg['To'] = to_addr
    msg.set_content(f'''Your payment was confirmed.\n\nDownload: {url}\n\nThis link works once and expires in {int(os.environ.get('BEACON_SOL_TOKEN_TTL', '172800')) // 3600} hours.\n\nBeacon\n''')
    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if user:
                smtp.login(user, password or '')
            smtp.send_message(msg)
        return True, 'sent'
    except Exception as exc:
        return False, f'email failed: {type(exc).__name__}'


def _issue_token(conn, order):
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expiry = _utc(time.time() + TOKEN_TTL)
    conn.execute('UPDATE orders SET token_hash=?, token_expires_at=?, token_used_at=NULL WHERE id=?', (token_hash, expiry, order['id']))
    return token


def _deliver(order_id):
    """Issue a fresh token and try to email it. Safe to call repeatedly for
    the same order: a prior *successful* send already flipped status to
    'fulfilled', which the status filter below excludes, and a prior
    *failed* send is retried at most once per EMAIL_RETRY_SECONDS (gated on
    email_attempted_at, set before the send attempt so overlapping callers
    -- the monitor loop and a same-instant HTTP verify -- can't double-send).
    Each retry issues a new token rather than reusing the old one: only the
    token's hash is ever persisted, so the plaintext from a failed attempt
    is already gone."""
    with _db_lock:
        conn = _db(); row = conn.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
        if not row or row['status'] not in ('paid_pending_email', 'paid'):
            conn.close(); return
        if row['email_attempted_at'] and time.time() - _parse_ts(row['email_attempted_at']) < EMAIL_RETRY_SECONDS:
            conn.close(); return
        token = _issue_token(conn, row)
        conn.execute('UPDATE orders SET email_attempted_at=? WHERE id=?', (_utc(), order_id))
        conn.commit(); conn.close()
    ok, detail = _send_email(row['email'], PRODUCTS[row['product']]['title'], token)
    with _db_lock:
        conn = _db()
        if ok:
            conn.execute("UPDATE orders SET status='fulfilled', email_status='sent', last_error=NULL WHERE id=?", (order_id,))
        else:
            conn.execute("UPDATE orders SET status='paid_pending_email', email_status='error', last_error=? WHERE id=?", (detail, order_id))
        conn.commit(); conn.close()


def retry_stalled_email():
    """Re-attempt delivery for orders that paid but never got their email --
    a real customer already paid, so a single SMTP hiccup shouldn't strand
    them forever. `_deliver`'s own email_attempted_at gate keeps this from
    resending faster than EMAIL_RETRY_SECONDS."""
    with _db_lock:
        conn = _db()
        rows = conn.execute("SELECT id FROM orders WHERE status='paid_pending_email' AND email_status='error'").fetchall()
        conn.close()
    for row in rows:
        _deliver(row['id'])


def create_order(product, email):
    if product not in PRODUCTS:
        raise ValueError('unknown product')
    email = str(email or '').strip().lower()
    if not EMAIL_RE.fullmatch(email):
        raise ValueError('valid email is required')
    now = time.time(); order_id = 'ord_' + secrets.token_hex(12); reference = _b58(secrets.token_bytes(32))
    created, expires = _utc(now), _utc(now + ORDER_TTL)
    with _db_lock:
        conn = _db()
        conn.execute('INSERT INTO orders (id,product,email,amount_lamports,reference,created_at,expires_at,status) VALUES (?,?,?,?,?,?,?,?)', (order_id, product, email, PRODUCTS[product]['amount_lamports'], reference, created, expires, 'pending'))
        conn.commit(); row = conn.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone(); conn.close()
    amount = row['amount_lamports'] / 1_000_000_000
    query = urllib.parse.urlencode({'amount': f'{amount:.9f}'.rstrip('0').rstrip('.'), 'reference': reference, 'label': 'Beacon', 'message': PRODUCTS[product]['title']})
    data = _row_public(row); data['payment_uri'] = f'solana:{WALLET}?{query}'; return data


def get_order(order_id):
    with _db_lock:
        conn = _db(); row = conn.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone(); conn.close()
    return _row_public(row) if row else None


def verify_order(order_id, signature):
    with _db_lock:
        conn = _db(); row = conn.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone(); conn.close()
    if not row:
        return None, 'order not found'
    if row['status'] in ('paid', 'paid_pending_email', 'fulfilled'):
        return _row_public(row), 'already verified'
    ok, reason = verify_signature(signature, row)
    if not ok:
        return _row_public(row), reason
    with _db_lock:
        conn = _db(); conn.execute("UPDATE orders SET status='paid_pending_email', signature=?, last_error=NULL WHERE id=? AND status='pending'", (signature, order_id)); conn.commit(); conn.close()
    _deliver(order_id)
    return get_order(order_id), 'payment verified'


def download(token):
    """Returns file info exactly once per issued token -- the token is
    marked consumed here, before the caller streams the file, so a second
    attempt (replay, shared link, retry-after-success) always fails. This
    is the fix for the earlier version's "one-time" claim, which was
    previously untrue (reusable until the 48h expiry)."""
    token_hash = hashlib.sha256((token or '').encode()).hexdigest()
    with _db_lock:
        conn = _db()
        row = conn.execute('SELECT * FROM orders WHERE token_hash=?', (token_hash,)).fetchone()
        if not row or row['status'] != 'fulfilled' or row['token_used_at'] \
                or time.time() > _parse_ts(row['token_expires_at']):
            conn.close(); return None
        product = PRODUCTS.get(row['product'])
        path = PAID_ROOT / product['file']
        if not path.is_file() or path.parent != PAID_ROOT:
            conn.close(); return None
        conn.execute('UPDATE orders SET token_used_at=? WHERE id=? AND token_used_at IS NULL', (_utc(), row['id']))
        conn.commit()
        consumed = conn.total_changes > 0
        conn.close()
    if not consumed:
        return None  # lost a race with a concurrent download of the same token
    return {'path': path, 'type': product['type'], 'filename': path.name, 'title': product['title']}


def purge_expired():
    """Delete orders that can no longer do anything useful: never-paid
    orders past their order expiry, and long-since-fulfilled orders kept
    only for the audit/support retention window. Runs once per monitor
    cycle -- the earlier version had no cleanup path at all, so stale rows
    accumulated forever."""
    cutoff = _utc(time.time() - ORDER_RETENTION_SECONDS)
    with _db_lock:
        conn = _db()
        conn.execute("DELETE FROM orders WHERE status='pending' AND expires_at < ?", (_utc(),))
        conn.execute("DELETE FROM orders WHERE status='fulfilled' AND created_at < ?", (cutoff,))
        conn.commit(); conn.close()


def poll_once():
    with _db_lock:
        conn = _db(); rows = conn.execute("SELECT * FROM orders WHERE status='pending' AND expires_at > ? ORDER BY created_at LIMIT 100", (_utc(),)).fetchall(); conn.close()
    if rows:
        try:
            recent = _rpc('getSignaturesForAddress', [WALLET, {'limit': MAX_RPC_SIGNATURES, 'commitment': 'confirmed'}]) or []
        except Exception:
            _log(f"getSignaturesForAddress failed: {traceback.format_exc(limit=3)}")
        else:
            signatures = [r.get('signature') for r in recent if r.get('confirmationStatus') in ('confirmed', 'finalized') and not r.get('err')]
            for row in rows:
                for signature in signatures:
                    ok, _ = verify_signature(signature, row)
                    if ok:
                        verify_order(row['id'], signature); break
    retry_stalled_email()
    purge_expired()


def start_monitor():
    def loop():
        while True:
            try:
                poll_once()
            except Exception:
                _log(f"monitor loop error: {traceback.format_exc(limit=5)}")
            time.sleep(POLL_SECONDS)
    thread = threading.Thread(target=loop, name='sol-payment-monitor', daemon=True); thread.start(); return thread
