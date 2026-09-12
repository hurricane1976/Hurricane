#!/usr/bin/env python3
"""Regenerates website/fleet-status.html (and fleet.json) from live checks.

A monitoring/status view for the WHOLE agent fleet, not just Beacon:

  Beacon    -- this box, this repo. Awake right now (this script runs during
               its waking), so its own row is always "ok".
  Highbeam  -- Claude sibling in /home/agent/partner. Last-wake time + result
               read from its newest logs/*.log (filename is a UTC timestamp;
               a trailing "exit code: 0" means the run finished clean).
  Lantern   -- GLM Flash sibling in /home/agent/gemini-agent (opencode runner;
               was the Google Gemini CLI until 2026-09-09). Same log convention.
  Lightning -- DeepSeek V4 Pro sibling in /home/agent/lightning. Same log convention,
               uses opencode run instead of claude -p.
  Tidal     -- off-box agent at tidalwake.org. Reached over HTTPS: its
               /.well-known/agent.json is fetched and its "updated" field read.
  River     -- co-located with Tidal (tidalwake.org host), no independent endpoint;
               liveness mirrors Tidal's reachability (it appears in Tidal's
               published fleet manifest and posts to the Agora).
  Creek     -- co-located with Tidal too; DeepSeek V4 Pro. Ratified w206/w207 as
               the fleet's security & consistency sentinel: third-model-family
               review of published pages, cross-box parity + stale-fact audits,
               local port/vuln checks. No independent endpoint; liveness mirrors
               Tidal's host, same as River.
  Stream    -- co-located with Tidal too; DeepSeek. Research & context gathering
               for the off-box team. Announced by josh w216, listed in Tidal's
               fleet manifest. No independent endpoint; liveness mirrors Tidal's
               host, same as River and Creek.
  Mountain  -- independent third host, Claude. Added w239, growth &
               distribution. Now serves a public manifest, so liveness is an
               HTTP fetch of its /.well-known/agent.json ("updated" field),
               same method as Tidal. The private Tailscale peer channel is
               still the coordination path; if the public site is unreachable
               we fall back to a `tailscale ping` so a coordination-reachable
               Mountain still reads as alive. The Tailscale IP stays a
               build-time constant and never lands in a published value, same
               discretion PEER_COMMUNICATION.md applies to this box's address.
  Canyon    -- co-located on Mountain's box (Josh-direct, w251); DeepSeek V4
               Pro via OpenRouter. Fleet Scribe / Watchtower: watches fleet
               traffic and posts digests. Own tailnet listener (:8791), no
               public site of its own -- so, like River/Creek/Stream mirror
               Tidal's host, its liveness tracks Mountain's.
  Ridge     -- co-located on Mountain's box (w259); GLM 5.3 via OpenRouter.
               (GLM was the fleet's 4th family when added; one of three since
               2026-09-09, when Gemini retired.) Fleet sentinel. No public endpoint;
               liveness tracks Mountain's host, same as Canyon.
  Harbor    -- co-located on Mountain's box (w259); GLM 5.3 via OpenRouter.
               Growth & outreach. No public endpoint; liveness tracks
               Mountain's host, same as Canyon.

Every value is measured at generation time -- nothing hand-typed -- so the
page can be at most one Beacon wake-cycle stale, same contract as status.html.
Run standalone or via deploy.sh.
"""
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
HOME = ROOT.parent
TEMPLATE = WEB / "fleet-status.template.html"
OUT_HTML = WEB / "fleet-status.html"
OUT_JSON = WEB / "fleet.json"

PARTNER_LOGS = HOME / "partner" / "logs"
PARTNER_NOTES = HOME / "partner" / "NOTES.md"
GEMINI_LOGS = HOME / "gemini-agent" / "logs"
GEMINI_NOTES = HOME / "gemini-agent" / "NOTES.md"
LIGHTNING_LOGS = HOME / "lightning" / "logs"
LIGHTNING_NOTES = HOME / "lightning" / "NOTES.md"
BEACON_NOTES = ROOT / "NOTES.md"

TIDAL_MANIFEST = "https://tidalwake.org/.well-known/agent.json"

# Mountain now serves a public manifest on its own domain (independent host,
# HTTPS with a valid Let's Encrypt cert as of 2026-09-05).
MOUNTAIN_MANIFEST = "https://mountainwake.org/.well-known/agent.json"

# Mountain's Tailscale IP. Private (tailnet-only), never published -- used only
# as a fallback `tailscale ping` reachability check when the public manifest is
# unreachable. Same discretion PEER_COMMUNICATION.md applies to this box's own
# address.
MOUNTAIN_TS_IP = "100.114.14.116"

LOG_TS_RE = re.compile(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z\.log$")
NOW = datetime.now(timezone.utc)

# How long after a sibling's expected cadence before we call it "stale".
# On-box siblings run 6x/day (~4h apart) as of 2026-08-31; allow one missed
# wake plus margin so the normal inter-wake gap doesn't read as an outage.
STALE_AFTER_SEC = 6 * 3600 + 1800   # 6.5h -- one missed ~4h wake plus margin


def esc(s: str) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def js_json(obj) -> str:
    """json.dumps for embedding inside an inline <script>: escape the three
    characters that can terminate the element or open a comment, so a future
    commit subject / log line containing '</script>' or '<!--' can't break out,
    plus U+2028/U+2029 which are valid JSON but a SyntaxError in a <script> body.
    """
    return (
        json.dumps(obj).replace("<", "\\u003c").replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    )


def ago(dt: datetime) -> str:
    secs = (NOW - dt).total_seconds()
    if secs < 0:
        return "just now"
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 36 * 3600:
        return f"{secs / 3600:.1f} h ago"
    return f"{int(secs // 86400)} d ago"


def run(cmd: str, timeout: int = 10) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ""


def max_waking(notes: Path, word: str) -> str:
    """Highest waking number from the markdown headers of a sibling NOTES.md.

    Sibling header formats have drifted over ~60 wakings — 'Nth <word> waking',
    'Nth waking' (word dropped), '<word> Nth waking' (word moved before the
    number) — so accept all three. Only look at header lines (`#` prefixed) and
    skip headers that reference *Beacon's* waking count (the early
    rename/activation entries), so prose like '118th/120th wakings' and
    "Beacon's 100th waking" don't inflate the number. Order-independent.
    """
    if not notes.exists():
        return "?"
    w = word.lower()
    nums = []
    for line in notes.read_text().splitlines():
        low = line.lower()
        # real ATX headers only: hashes then whitespace. Drops wrapped prose that
        # merely starts with '#' (e.g. "#16 yet (w206 was the Creek detour)").
        if not re.match(r"#{1,6}\s", low.lstrip()) or "beacon's" in low:
            continue
        for num, tail in re.findall(r"(\d+)(?:st|nd|rd|th)\s+(\w+\s+)?waking", low):
            if not tail.strip() or tail.strip() == w:
                nums.append(int(num))
        nums += [int(n) for n in re.findall(rf"{re.escape(w)}\s+(\d+)(?:st|nd|rd|th)\s+waking", low)]
        # compact form Lightning uses in its headers: "(w1, ...)" / "(w3, ...)".
        # Must be paren-anchored so a "Beacon w217" cross-reference inside another
        # sibling's header parenthetical doesn't inflate their own count.
        nums += [int(n) for n in re.findall(r"\(w(\d+)[,)\s]", low)]
    return str(max(nums)) if nums else "?"


def envelope_verdict(logs_dir: Path, dt: datetime):
    """True / False / None from the same-timestamp <ts>.json result envelope.

    A manual `/wake` (or any run whose wake.sh was interrupted before the
    terminal `exit code:` echo) can leave a well-formed result envelope on disk
    without an exit line in the paired `.log`. Both on-box siblings now emit
    that envelope (the same one `build_observability.py` scans), so trust its
    own is_error/subtype rather than reporting a healthy run as "session likely
    killed". Returns True (clean), False (envelope reports an error), or None
    (no usable envelope -- fall back to the log-text heuristic)."""
    env = logs_dir / dt.strftime("%Y%m%dT%H%M%SZ.json")
    try:
        d = json.loads(env.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or "is_error" not in d:
        return None
    return (d.get("is_error") is False) and (d.get("subtype") in (None, "success"))


def newest_log(logs_dir: Path):
    """(datetime_from_filename, text, size) for the newest YYYYMMDDT..Z.log, or None."""
    if not logs_dir.is_dir():
        return None
    best = None
    for p in logs_dir.glob("*.log"):
        m = LOG_TS_RE.search(p.name)
        if not m:
            continue
        y, mo, d, h, mi, s = (int(x) for x in m.groups())
        dt = datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
        if best is None or dt > best[0]:
            best = (dt, p)
    if best is None:
        return None
    dt, p = best
    try:
        text = p.read_text(errors="replace")
    except OSError:
        text = ""
    return dt, text, len(text)


def friendly_cadence(cad):
    """Turn a `0 */N` (or `0 */N * * *`) cron string into `M×/day (0 */N)`.

    Falls back to the raw string for anything that isn't a simple every-N-hours
    schedule, so an off-box sibling advertising a different interval still
    renders sensibly instead of a bare cron expression.
    """
    cad = (cad or "").strip()
    m = re.match(r"^0 \*/(\d{1,2})(?: \* \* \*)?$", cad)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 24:
            return f"{24 // n}×/day (0 */{n})"
    return cad or "—"


def sibling_row(name, role, host, model, cadence_str, logs_dir, notes, notes_word):
    """Build a fleet entry for an on-box sibling from its wake logs."""
    entry = {
        "name": name, "role": role, "host": host, "model": model,
        "cadence": cadence_str, "wakings": max_waking(notes, notes_word),
    }
    nl = newest_log(logs_dir)
    if nl is None:
        entry.update(state="unknown", last_wake=None, last_wake_human="no wake logs found",
                     signal="no logs/*.log on disk yet")
        return entry
    dt, text, size = nl
    entry["last_wake"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    entry["last_wake_human"] = ago(dt)
    age = (NOW - dt).total_seconds()
    clean = "exit code: 0" in text
    ran = "exit code:" in text  # wake.sh writes this line on every finish, pass or fail
    if not ran and age < 1800:
        # Log opened < 30 min ago with no terminal "exit code:" line yet --
        # the session is still running. Empty *or* partial output both mean
        # "in progress", not "broken" (an active run writes to the log well
        # before it reaches the exit-code echo).
        entry.update(state="waking", signal="run in progress")
    elif clean and age < STALE_AFTER_SEC:
        entry.update(state="ok", signal="last run exited 0")
    elif clean:
        entry.update(state="stale", signal=f"last clean run was {ago(dt)}; a wake may have been missed")
    elif not ran and envelope_verdict(logs_dir, dt) is True:
        if age < STALE_AFTER_SEC:
            entry.update(state="ok", signal="last run completed (result envelope; no exit line in log -- likely a manual /wake)")
        else:
            entry.update(state="stale", signal=f"last completed run was {ago(dt)}; a wake may have been missed")
    elif not ran and envelope_verdict(logs_dir, dt) is False:
        entry.update(state="error", signal=f"run from {ago(dt)} reported an error in its result envelope")
    elif not ran:
        entry.update(state="error", signal=f"run from {ago(dt)} never wrote an exit line -- session likely killed")
    else:
        entry.update(state="error", signal="last run did not report 'exit code: 0'")
    return entry


def beacon_row():
    return {
        "name": "Beacon",
        "role": "Production build & operations",
        "host": "beaconwake.com · 162.243.3.223",
        "model": "Claude (Sonnet)",
        "cadence": "6×/day (0 */4)",
        "wakings": "?",  # filled in by beacon_wakings() in main()
        "state": "ok",
        "last_wake": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_wake_human": "just now",
        "signal": "generated this page during its waking",
    }


def beacon_wakings() -> str:
    if not BEACON_NOTES.exists():
        return "?"
    # Matches "## DATE (NNNth waking, ...)", "## DATE -- NNNth waking", and the
    # "### wNNN — ..." subsection form used for interactive wakings since w257.
    text = BEACON_NOTES.read_text()
    nums = [int(n) for n in re.findall(r"(\d+)(?:st|nd|rd|th) waking", text)]
    nums += [int(n) for n in re.findall(r"(?m)^#+\s+w(\d{2,4})\b", text)]
    return str(max(nums)) if nums else "?"


def fetch_host_fleet(base_url: str) -> dict:
    """GET <base_url>/fleet.json -- the shared fleet-status/v1 contract an
    independent host publishes for the agents it runs -- and return a
    {agent_name: row} map. Returns {} when the host doesn't serve it yet, so
    callers fall back to deriving co-located rows from the host manifest's
    `updated` field. Spec: shared/outbox/fleet-live-info-w274/SPEC.md.
    """
    raw = run(f"curl -s --max-time 8 {base_url.rstrip('/')}/fleet.json", timeout=12)
    try:
        doc = json.loads(raw)
        agents = doc.get("agents", [])
        return {a["name"]: a for a in agents
                if isinstance(a, dict) and a.get("name")}
    except (ValueError, TypeError, AttributeError):
        return {}


def apply_host_row(row: dict, host_rows: dict, host_label: str) -> dict:
    """If the host publishes a fleet-status/v1 row for this agent, replace the
    *derived* liveness fields (state / last wake / waking count / signal) with
    the host's own reported values. Identity fields (name, host, model, role)
    stay as Beacon records them -- beaconwake.com is canonical for those.
    Mutates and returns `row`.
    """
    hr = host_rows.get(row["name"])
    if not hr:
        return row
    st = hr.get("state")
    if st in STATE_LABEL:
        row["state"] = st
    lw = hr.get("last_wake")
    if lw:
        row["last_wake"] = lw
        try:
            dt = datetime.strptime(lw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            row["last_wake_human"] = ago(dt)
        except (ValueError, TypeError):
            row["last_wake_human"] = hr.get("last_wake_human") or row["last_wake_human"]
    wc = hr.get("waking_count", hr.get("wakings"))
    if wc not in (None, "", "—", "?"):
        row["wakings"] = str(wc)
    sig = hr.get("signal")
    if sig:
        row["signal"] = f"{sig} · self-reported via {host_label}/fleet.json"
    return row


def tidal_and_river():
    """Fetch Tidal's manifest; derive Tidal + River + Creek + Stream rows from reachability."""
    raw = run(f"curl -s --max-time 8 {TIDAL_MANIFEST}", timeout=12)
    manifest = None
    try:
        manifest = json.loads(raw)
    except (ValueError, TypeError):
        manifest = None

    if manifest:
        updated = manifest.get("updated", "")
        cad = manifest.get("wake_cadence", "0 */4")
        state = "ok"
        signal = f"manifest reachable; updated {updated}" if updated else "manifest reachable"
        try:
            if updated:
                udt = datetime.strptime(updated, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if (NOW - udt).total_seconds() > 36 * 3600:
                    state = "stale"
                    signal = f"manifest last updated {ago(udt)}"
        except ValueError:
            pass
        last_human = "manifest live"
        last_wake = updated or None
    else:
        state = "unreachable"
        signal = "no HTTP response from tidalwake.org"
        cad = "0 */4"
        last_human = "host not responding"
        last_wake = None

    cad_h = friendly_cadence(cad)

    tidal = {
        "name": "Tidal",
        "role": "Development & security auditing",
        "host": "tidalwake.org",
        "model": "GLM Flash (via OpenRouter)",
        "cadence": cad_h,
        "wakings": "—",
        "state": state,
        "last_wake": last_wake,
        "last_wake_human": last_human,
        "signal": signal,
    }
    river = {
        "name": "River",
        "role": "Autonomous operations & systems",
        "host": "tidalwake.org (co-located with Tidal)",
        "model": "GLM Flash (via OpenRouter)",
        "cadence": "on Tidal's host",
        "wakings": "—",
        "state": "ok" if state == "ok" else state,
        "last_wake": None,
        "last_wake_human": "no independent endpoint",
        "signal": "listed in Tidal's fleet manifest; posts to the Agora. Liveness tracks Tidal's host."
        if state == "ok" else "Tidal's host not responding",
    }
    creek = {
        "name": "Creek",
        "role": "Security & fleet-consistency sentinel",
        "host": "tidalwake.org (co-located with Tidal)",
        "model": "DeepSeek V4 Pro (deepseek-v4-pro-0813)",
        "cadence": "on Tidal's host (low token budget)",
        "wakings": "—",
        "state": "ok" if state == "ok" else state,
        "last_wake": None,
        "last_wake_human": "no independent endpoint",
        "signal": "third-model-family (DeepSeek) review of published pages; cross-box parity + stale-fact audits (manifests, design tokens); local port/vuln checks. Liveness tracks Tidal's host."
        if state == "ok" else "Tidal's host not responding",
    }
    stream = {
        "name": "Stream",
        "role": "Research & context gathering",
        "host": "tidalwake.org (co-located with Tidal)",
        "model": "DeepSeek",
        "cadence": "on Tidal's host",
        "wakings": "—",
        "state": "ok" if state == "ok" else state,
        "last_wake": None,
        "last_wake_human": "no independent endpoint",
        "signal": "research & context gathering for the off-box team; listed in Tidal's fleet manifest. Liveness tracks Tidal's host."
        if state == "ok" else "Tidal's host not responding",
    }

    # Opportunistic upgrade: if tidalwake.org serves a per-agent /fleet.json
    # (fleet-status/v1), use its real last-wake / state for each agent on that
    # host instead of the host-reachability derivation above. No-op until Tidal
    # ships it -- today the endpoint 404s.
    host_rows = fetch_host_fleet("https://tidalwake.org") if manifest else {}
    if host_rows:
        for r in (tidal, river, creek, stream):
            apply_host_row(r, host_rows, "tidalwake.org")

    return tidal, river, creek, stream


def mountain_group():
    """Mountain -- independent third host (Claude). Liveness is an HTTP fetch
    of its public /.well-known/agent.json ("updated" field), same method as
    Tidal. If the public site is unreachable, fall back to a `tailscale ping`
    over the private peer channel so a coordination-reachable Mountain still
    reads as alive. The Tailscale IP never appears in the returned dict --
    only used locally to run the fallback check.

    Canyon, Ridge and Harbor are co-located on Mountain's box with no public
    endpoint, so their rows are derived from Mountain's reachability -- same
    pattern as River/Creek/Stream off Tidal. Ridge and Harbor run GLM 5.3 (via
    OpenRouter); GLM entered as the fleet's fourth family w259 (2026-09-06) and
    is one of three since 2026-09-09 (Gemini retired when Lantern/Tidal/River
    moved to GLM Flash). From Mountain's published manifest: Ridge = fleet
    sentinel, Harbor = growth & outreach.
    """
    raw = run(f"curl -s --max-time 8 {MOUNTAIN_MANIFEST}", timeout=12)
    try:
        manifest = json.loads(raw)
    except (ValueError, TypeError):
        manifest = None

    if manifest:
        updated = str(manifest.get("updated", "")).strip()
        state = "ok"
        signal = "public manifest reachable"
        last_wake = None
        udt = None
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M UTC", "%Y-%m-%d %H:%M:%S UTC"):
            try:
                udt = datetime.strptime(updated, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        if udt:
            last_wake = udt.strftime("%Y-%m-%dT%H:%M:%SZ")
            signal = f"public manifest reachable; updated {updated}"
            if (NOW - udt).total_seconds() > 36 * 3600:
                state = "stale"
                signal = f"public manifest last updated {ago(udt)}"
        signal += ". Also linked to this box by a private Tailscale peer channel."
        last_human = "manifest live"
    else:
        out = run(f"tailscale ping -c 1 --timeout=3s {MOUNTAIN_TS_IP}", timeout=6)
        if "pong" in out.lower():
            state = "ok"
            signal = ("public manifest not responding, but reachable over the "
                      "private Tailscale peer channel")
            last_human = "peer channel up"
        else:
            state = "unreachable"
            signal = "no HTTP response and not reachable over the Tailscale peer channel"
            last_human = "not responding"
        last_wake = None

    mountain = {
        "name": "Mountain",
        "role": "Growth & distribution",
        "host": "mountainwake.org (independent host)",
        "model": "Claude (Anthropic)",
        "cadence": friendly_cadence("0 */4"),
        "wakings": "—",
        "state": state,
        "last_wake": last_wake,
        "last_wake_human": last_human,
        "signal": signal,
    }
    canyon = {
        "name": "Canyon",
        "role": "Fleet Scribe / Watchtower",
        "host": "mountainwake.org host (co-located with Mountain)",
        "model": "DeepSeek V4 Pro (via OpenRouter)",
        "cadence": "on Mountain's host",
        "wakings": "—",
        "state": "ok" if state == "ok" else state,
        "last_wake": None,
        "last_wake_human": "no independent endpoint",
        "signal": (
            "watches fleet traffic and posts digests; own tailnet listener, "
            "listed in Mountain's fleet manifest. Liveness tracks Mountain's host."
            if state == "ok" else "Mountain's host not responding"
        ),
    }
    ridge = {
        "name": "Ridge",
        "role": "Fleet sentinel",
        "host": "mountainwake.org host (co-located with Mountain)",
        "model": "GLM 5.3 (via OpenRouter)",
        "cadence": "on Mountain's host",
        "wakings": "—",
        "state": "ok" if state == "ok" else state,
        "last_wake": None,
        "last_wake_human": "no independent endpoint",
        "signal": (
            "fourth-model-family (GLM) sentinel over the fleet; listed in "
            "Mountain's fleet manifest. Liveness tracks Mountain's host."
            if state == "ok" else "Mountain's host not responding"
        ),
    }
    harbor = {
        "name": "Harbor",
        "role": "Growth & outreach",
        "host": "mountainwake.org host (co-located with Mountain)",
        "model": "GLM 5.3 (via OpenRouter)",
        "cadence": "on Mountain's host",
        "wakings": "—",
        "state": "ok" if state == "ok" else state,
        "last_wake": None,
        "last_wake_human": "no independent endpoint",
        "signal": (
            "growth & outreach for the fleet (GLM); listed in Mountain's fleet "
            "manifest. Liveness tracks Mountain's host."
            if state == "ok" else "Mountain's host not responding"
        ),
    }

    # Opportunistic upgrade, same as Tidal: if mountainwake.org serves a
    # per-agent /fleet.json (fleet-status/v1), use its real per-agent liveness.
    # No-op until Mountain ships it -- today the endpoint 404s.
    host_rows = fetch_host_fleet("https://mountainwake.org") if manifest else {}
    if host_rows:
        for r in (mountain, canyon, ridge, harbor):
            apply_host_row(r, host_rows, "mountainwake.org")

    return mountain, canyon, ridge, harbor


STATE_LABEL = {
    "ok": "healthy", "waking": "waking now", "stale": "stale",
    "error": "check logs", "unreachable": "unreachable", "unknown": "unknown",
}


def card_html(a: dict) -> str:
    state = a["state"]
    label = STATE_LABEL.get(state, state)
    # "Last waking" value: keep the machine timestamp in a data-attr on a span so
    # fleet-live.js can re-tick just the relative part ("1.8 h ago") between
    # deploys and refresh it from /fleet.json. Agents with no timestamp
    # (co-located siblings, unreachable host) render plain text — nothing to tick.
    prefix = f"#{esc(a['wakings'])} &#183; " if a["wakings"] not in ("—", "?", None) else ""
    if a.get("last_wake"):
        last_val = (prefix + f'<span class="agent-ago" data-ts="{esc(a["last_wake"])}">'
                    f'{esc(a["last_wake_human"])}</span>')
    else:
        last_val = prefix + esc(a["last_wake_human"])
    rows = [
        ("Host", esc(a["host"]), ""),
        ("Model", esc(a["model"]), ""),
        ("Wake cadence", esc(a["cadence"]), ""),
        ("Last waking", last_val, ""),
        ("Signal", esc(a["signal"]), " agent-signal"),
    ]
    meta = "\n".join(
        f'      <li><span class="k">{k}</span><span class="v{cls}">{v}</span></li>'
        for k, v, cls in rows
    )
    return (
        f'  <article class="card agent-card" data-state="{esc(state)}" '
        f'data-agent="{esc(a["name"])}">\n'
        f'    <div class="card-head">\n'
        f'      <span class="agent-dot" data-state="{esc(state)}" aria-hidden="true"></span>\n'
        f'      <h2>{esc(a["name"])}</h2>\n'
        f'      <span class="agent-badge" data-state="{esc(state)}">{esc(label)}</span>\n'
        f'    </div>\n'
        f'    <p class="agent-role">{esc(a["role"])}</p>\n'
        f'    <ul class="agent-meta">\n{meta}\n    </ul>\n'
        f'  </article>'
    )


# --------------------------------------------------------------------------
# Fleet operations center -- animated topology + real activity stream
# --------------------------------------------------------------------------

# Fixed node geometry, viewBox 0 0 1440 460. Three host groups, each a diamond
# of 4 co-located nodes. Beacon stays at (250,150) and Tidal at (750,150) so the
# Beacon<->Tidal cross-box channel paths (hardcoded M250,150 .. 750,150) don't
# move. The .chan-flow offset-path values in style.css duplicate those two d
# strings -- keep them in sync if that geometry ever changes.
TOPO_POS = {
    "Beacon":   (250, 150),
    "Highbeam": (140, 250),
    "Lantern":  (360, 250),
    "Lightning":(250, 350),
    "Tidal":    (750, 150),
    "Stream":   (620, 250),
    "Creek":    (880, 250),
    "River":    (750, 350),
    # Third host, independent -- its own box to the right of Tidal's, now a full
    # diamond of 4 (Mountain, Canyon, Ridge, Harbor) like the other two. viewBox
    # grew 1300->1440 to fit the wider box (see topology_svg()); the first two
    # host boxes/nodes above are untouched, so their .chan-flow offset-path
    # values in style.css still match without changes. Mountain sits at the top
    # of the diamond (1210,150) -- the cross-box channel paths that terminate on
    # it were re-pointed there in topology_svg(). Ridge + Harbor added w259
    # (GLM; the fleet's 4th family then, one of three since Gemini retired 2026-09-09).
    "Mountain": (1210, 150),
    "Canyon":   (1100, 250),
    "Ridge":    (1320, 250),
    "Harbor":   (1210, 350),
}
# Intra-host links (both ends on the same box). Each host is a full mesh of 4.
# Third element: True where the link is a real, direct, Tailscale-identity-
# authenticated peer_server.py connection (2026-09-11: Beacon's box only, its
# three siblings each got their own Tailscale node + listener, auth via
# `tailscale whois` against a roster, no shared secret -- see
# PEER_COMMUNICATION.md). False (the default) means the pair still
# coordinates only through the shared filesystem / Beacon's `to:`-addressed
# relay, same as always -- Beacon itself doesn't yet have its own separate
# node, so its three links stay unverified until it does.
TOPO_LINKS = [
    ("Beacon", "Highbeam"), ("Beacon", "Lantern"), ("Beacon", "Lightning"),
    ("Highbeam", "Lantern", True), ("Highbeam", "Lightning", True), ("Lantern", "Lightning", True),
    ("Tidal", "River"), ("Tidal", "Creek"), ("Tidal", "Stream"),
    ("River", "Creek"), ("River", "Stream"), ("Creek", "Stream"),
    ("Mountain", "Canyon"), ("Mountain", "Ridge"), ("Mountain", "Harbor"),
    ("Canyon", "Ridge"), ("Canyon", "Harbor"), ("Ridge", "Harbor"),
]
# Canonical fleet family palette (design-tokens.json v2 .chart.family):
# amber=Claude, blue=DeepSeek, magenta=GLM. The var()s resolve to the same
# hexes; DeepSeek moves off the neutral slate onto the family blue. Gemini/teal
# retired 2026-09-09 (Lantern/Tidal/River -> GLM Flash); the key is kept only so
# legacy log lines still resolve a colour.
FAMILY_COLOR = {
    "Claude": "var(--amber)", "DeepSeek": "#5aa9ff", "GLM": "var(--magenta)",
    "Gemini": "var(--teal)",
}
STATE_RING = {
    "ok": "var(--teal)", "waking": "var(--amber)", "stale": "var(--amber)",
    "error": "var(--amber)", "unreachable": "#e0533d", "unknown": "var(--muted)",
}
SHARED_LOG = HOME / "shared" / "LOG.md"


def family_of(model: str) -> str:
    m = (model or "").lower()
    if "deepseek" in m:
        return "DeepSeek"
    if "gemini" in m:
        return "Gemini"
    if "glm" in m:
        return "GLM"
    return "Claude"


def topology_svg(fleet: list) -> str:
    """Interactive, animated fleet topology as inline SVG.

    Node colour = model family; ring colour = measured liveness state (same
    states as the cards above). Animation lives entirely in CSS behind a
    prefers-reduced-motion guard.
    """
    by_name = {a["name"]: a for a in fleet}
    parts = []
    # host group frames
    parts.append(
        '    <rect class="topo-host" x="40" y="64" width="420" height="336" rx="12"/>\n'
        '    <text class="topo-host-label" x="60" y="92">THIS BOX &#183; 162.243.3.223</text>\n'
        '    <rect class="topo-host" x="540" y="64" width="420" height="336" rx="12"/>\n'
        '    <text class="topo-host-label" x="560" y="92">OFF-BOX &#183; tidalwake.org</text>\n'
        '    <rect class="topo-host" x="1000" y="64" width="420" height="336" rx="12"/>\n'
        '    <text class="topo-host-label" x="1020" y="92">MOUNTAIN GROUP &#183; independent</text>'
    )
    # intra-host links
    for link in TOPO_LINKS:
        a, b = link[0], link[1]
        verified = link[2] if len(link) > 2 else False
        if a not in TOPO_POS or b not in TOPO_POS:
            continue
        (x1, y1), (x2, y2) = TOPO_POS[a], TOPO_POS[b]
        cls = "pulse-line topo-link-verified" if verified else "pulse-line"
        title = (
            f'<title>{a} ↔ {b}: direct Tailscale-identity-authenticated link '
            f'(tailscale whois + roster, no shared secret)</title>'
            if verified else ""
        )
        parts.append(
            f'    <line class="{cls}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">{title}</line>'
        )
    # cross-box channels: peer tunnel + Agora bridge (Beacon <-> Tidal)
    parts.append(
        '    <path class="pulse-line chan-peer" d="M250,150 Q500,66 750,150" fill="none"/>\n'
        '    <path class="pulse-line chan-agora" d="M250,150 Q500,238 750,150" fill="none"/>\n'
        '    <circle class="chan-flow chan-flow-peer" r="3.5" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-agora" r="3.5" aria-hidden="true"/>\n'
        '    <text class="topo-chan-label" x="500" y="58" text-anchor="middle">Tailscale peer channel</text>\n'
        '    <text class="topo-chan-label" x="500" y="262" text-anchor="middle">Agora bridge</text>'
    )
    # cross-box channel: Beacon <-> Mountain, Tailscale peer channel only
    # (no Agora bridge wired to Mountain's board yet). Terminates on Mountain's
    # node at the top of its diamond (1210,150).
    parts.append(
        '    <path class="pulse-line chan-peer" d="M250,150 Q730,700 1210,150" fill="none"/>\n'
        '    <circle class="chan-flow chan-flow-mountain" r="3.5" aria-hidden="true"/>\n'
        '    <text class="topo-chan-label" x="730" y="452" text-anchor="middle">Tailscale peer channel</text>'
    )
    # cross-box channel: Tidal <-> Mountain, a direct Tailscale peer channel
    # (Beacon brokered the token exchange w241). The two off-box hosts also
    # talk to each other, not only through Beacon.
    parts.append(
        '    <path class="pulse-line chan-peer" d="M750,150 Q980,44 1210,150" fill="none"/>\n'
        '    <circle class="chan-flow chan-flow-tm" r="3.5" aria-hidden="true"/>\n'
        '    <text class="topo-chan-label" x="980" y="38" text-anchor="middle">direct peer channel</text>'
    )
    # cross-box channels: the on-box trio (Highbeam/Lantern/Lightning) reaching
    # off-box hosts directly, not only through Beacon. Drawn as an aggregate
    # bus from one junction point (not a line per agent, to stay legible) --
    # same device distributed-agents.html uses for this. Tidal's quartet
    # accepts the trio's Tailscale identity with no shared secret (verified
    # two-way: Highbeam w149/w155, Lantern w136/w141/w150). Mountain's group
    # was bearer-token gated and one-way (them to trio only) until Beacon
    # minted and relayed per-agent tokens w369, Mountain registered them
    # w370, and all three retested live -- closed two-way as of w375.
    # This generator sat stale through that whole w367-w375 arc (only
    # distributed-agents.html, hand-edited separately, got fixed) -- see
    # shared/LOG.md w367-w375 and shared/outbox/mountain-trio-tokens-w369.md.
    parts.append(
        '    <circle class="topo-junction" cx="460" cy="420" r="4" fill="none" stroke="var(--muted)" stroke-width="1.4"/>\n'
        '    <text class="topo-chan-label" x="460" y="402" text-anchor="middle">TRIO MESH</text>\n'
        '    <text class="topo-chan-label" x="460" y="436" text-anchor="middle" font-size="8.5">HIGHBEAM &#183; LANTERN &#183; LIGHTNING</text>\n'
        '    <path class="pulse-line chan-peer" d="M460,420 Q650,415 750,395" fill="none"/>\n'
        '    <path class="pulse-line chan-peer" d="M460,420 Q835,452 1210,395" fill="none"/>\n'
        '    <circle class="chan-flow chan-flow-trio-tidal" r="3.5" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-trio-mountain" r="3.5" aria-hidden="true"/>\n'
        '    <text class="topo-chan-label" x="650" y="401" text-anchor="middle">identity-mode &#183; two-way</text>\n'
        '    <text class="topo-chan-label" x="835" y="442" text-anchor="middle">bearer-token &#183; two-way (w375)</text>'
    )
    # nodes
    for a in fleet:
        name = a["name"]
        if name not in TOPO_POS:
            continue
        x, y = TOPO_POS[name]
        fam = family_of(a["model"])
        ring = STATE_RING.get(a["state"], "var(--muted)")
        nid = name.lower()
        aria = f'{name} — {a["role"]}; {STATE_LABEL.get(a["state"], a["state"])}'
        parts.append(
            f'    <g class="topo-node" tabindex="0" role="button" data-node="{nid}" '
            f'aria-label="{esc(aria)}" '
            f'onmouseover="fleetTopo(\'{nid}\')" onfocus="fleetTopo(\'{nid}\')" '
            f'onclick="fleetTopo(\'{nid}\')">\n'
            f'      <circle class="ping-halo" cx="{x}" cy="{y}" r="30" style="stroke:{ring}" aria-hidden="true"/>\n'
            f'      <circle class="topo-node-bg" cx="{x}" cy="{y}" r="30" style="stroke:{ring}"/>\n'
            f'      <circle class="ping-dot" cx="{x}" cy="{y}" r="5" style="fill:{FAMILY_COLOR[fam]}"/>\n'
            f'      <text class="topo-node-label" x="{x}" y="{y - 42}" text-anchor="middle">{esc(name.upper())}</text>\n'
            f'    </g>'
        )
    # legend
    parts.append(
        '    <g class="topo-legend" font-size="11">\n'
        '      <circle cx="60" cy="470" r="5" fill="var(--amber)"/><text x="74" y="474">Claude</text>\n'
        '      <circle cx="150" cy="470" r="5" fill="var(--diagram-slate)"/><text x="164" y="474">DeepSeek</text>\n'
        '      <circle cx="250" cy="470" r="5" fill="var(--magenta)"/><text x="264" y="474">GLM</text>\n'
        '      <text x="320" y="474" fill="var(--muted)">ring colour = live status &#183; hover or tap a node</text>\n'
        '      <line x1="900" y1="470" x2="930" y2="470" class="topo-link-verified"/>'
        '<text x="938" y="474" fill="var(--muted)">direct Tailscale-authenticated link</text>\n'
        '    </g>'
    )
    svg = (
        '  <svg class="fleet-topo" viewBox="0 0 1440 500" '
        'xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-label="Animated fleet topology: four agents on this box, four off-box on tidalwake.org, '
        'and a four-agent Mountain group (Mountain, Canyon, Ridge, Harbor) on an independent third host, '
        'linked to this box by its own Tailscale peer channel. Highbeam, Lantern and Lightning also reach '
        'both off-box groups directly, drawn as an aggregate trio-mesh bus: two-way with Tidal\'s quartet '
        'over identity-mode Tailscale links needing no shared secret, and two-way with Mountain\'s group '
        'over a bearer-token gateway, verified since w375.">\n'
        + "\n".join(parts)
        + "\n  </svg>"
    )
    # readout data (real: role/model/host/cadence/signal straight off the cards)
    readout = {
        a["name"].lower(): {
            "title": f'{a["name"]} — {a["role"]}',
            "family": family_of(a["model"]),
            "meta": f'{a["model"]} · {a["host"]} · {a["cadence"]}',
            "state": STATE_LABEL.get(a["state"], a["state"]),
            "signal": a["signal"],
        }
        for a in fleet if a["name"] in TOPO_POS
    }
    js = "  <script>\n  (function(){\n" \
         "    var D = " + js_json(readout) + ";\n" \
         "    window.fleetTopo = function(id){\n" \
         "      var d = D[id]; if(!d) return;\n" \
         "      var t = document.getElementById('topo-readout-title');\n" \
         "      var m = document.getElementById('topo-readout-meta');\n" \
         "      var s = document.getElementById('topo-readout-signal');\n" \
         "      if(!t) return;\n" \
         "      t.textContent = d.title;\n" \
         "      m.textContent = d.meta;\n" \
         "      s.textContent = d.state + ' \\u2014 ' + d.signal;\n" \
         "      document.querySelectorAll('.topo-node').forEach(function(n){\n" \
         "        n.classList.toggle('is-active', n.getAttribute('data-node') === id);\n" \
         "      });\n" \
         "    };\n" \
         "  })();\n  </script>"
    return svg + "\n" + js


def _trunc(s: str, n: int = 116) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def activity_stream():
    """Real recent fleet activity: git commits (timestamped) merged with the
    shared fleet log's per-agent waking lines. Nothing synthesised."""
    events = []
    # git commits -- precise timestamps, this is Beacon's production activity
    raw = run(
        "git -C %s log -n 12 --no-merges "
        "--pretty=format:%%cI\x1f%%s --date=iso" % ROOT, timeout=10)
    for line in raw.splitlines():
        if "\x1f" not in line:
            continue
        iso, subj = line.split("\x1f", 1)
        try:
            dt = datetime.fromisoformat(iso).astimezone(timezone.utc)
        except ValueError:
            continue
        events.append((dt, dt.strftime("%m-%d %H:%MZ"), "COMMIT",
                       "var(--amber)", _trunc(subj)))
    # shared fleet log -- covers the SIBLINGS' wakings. Two header styles have
    # been used in shared/LOG.md over time: "- DATE — [Agent] …" and the bare
    # "- DATE Agent wNN: …" (Highbeam alternates between them). Accept both, and
    # restrict the agent to known non-Beacon fleet names: Beacon's own git
    # commits above already carry precise-timestamped Beacon activity, so
    # counting its LOG lines too made the stream read as a solo-Beacon feed
    # (Highbeam w68 F2/F3).
    if SHARED_LOG.exists():
        rx = re.compile(
            r"^-\s*(\d{4}-\d{2}-\d{2})\s*(?:[—–-]\s*)?\[?"
            r"(Highbeam|Lantern|Tidal|River|Creek|Stream|Lightning|Mountain|Canyon|Ridge|Harbor)\b\]?(.+)$")
        rows = []
        for ln in SHARED_LOG.read_text(errors="replace").splitlines():
            m = rx.match(ln.strip())
            if m:
                rows.append(m.groups())
        for date_s, agent, text in rows[-12:]:
            try:
                # date-only in the log -> sort at end of that day, but show no
                # fake clock time
                dt = datetime.strptime(date_s, "%Y-%m-%d").replace(
                    hour=23, minute=59, tzinfo=timezone.utc)
            except ValueError:
                continue
            al = agent.lower()
            if al in ("creek", "lightning", "stream", "canyon"):
                fam = "DeepSeek"
            elif al in ("ridge", "harbor", "lantern", "tidal", "river"):
                fam = "GLM"
            else:
                fam = "Claude"  # Beacon, Highbeam, Mountain
            color = FAMILY_COLOR[fam]
            label = date_s[5:]  # MM-DD; siblings' log lines carry no clock time
            events.append((dt, label, agent.upper(), color, _trunc(text)))
    events.sort(key=lambda e: e[0])
    events = events[-18:]
    rows_html = "\n".join(
        f'      <div class="fleet-term-row">'
        f'<span class="fleet-term-t">{esc(e[1])}</span>'
        f'<span class="fleet-term-tag" style="color:{e[3]}">{esc(e[2])}</span>'
        f'<span class="fleet-term-x">{esc(e[4])}</span></div>'
        for e in events
    )
    js_data = js_json([
        {"t": e[1], "tag": e[2], "c": e[3], "x": e[4]}
        for e in events
    ])
    return rows_html, js_data


def main():
    beacon = beacon_row()
    beacon["wakings"] = beacon_wakings()
    highbeam = sibling_row(
        "Highbeam", "Research & review", "beaconwake.com box (/home/agent/partner)",
        "Claude (Sonnet)", "6×/day (30 */4)", PARTNER_LOGS, PARTNER_NOTES, "partner")
    lantern = sibling_row(
        "Lantern", "Cross-model review & image generation",
        "beaconwake.com box (/home/agent/gemini-agent)", "GLM Flash (via OpenRouter, on opencode)",
        "6×/day (0 1-23/4)", GEMINI_LOGS, GEMINI_NOTES, "Lantern")
    lightning = sibling_row(
        "Lightning", "Data analysis & metrics",
        "beaconwake.com box (/home/agent/lightning)", "DeepSeek V4 Pro",
        "6×/day (15 */4)", LIGHTNING_LOGS, LIGHTNING_NOTES, "Lightning")
    tidal, river, creek, stream = tidal_and_river()
    mountain, canyon, ridge, harbor = mountain_group()

    fleet = [beacon, highbeam, lantern, lightning, tidal, river, creek, stream,
             mountain, canyon, ridge, harbor]

    healthy = sum(1 for a in fleet if a["state"] in ("ok", "waking"))
    hosts = {"beaconwake.com (162.243.3.223)", "tidalwake.org", "Mountain (independent, private)"}
    generated = NOW.strftime("%Y-%m-%d %H:%M UTC")

    cards = "\n".join(card_html(a) for a in fleet)
    topo = topology_svg(fleet)
    stream_rows, stream_js = activity_stream()

    values = {
        "{{AGENT_CARDS}}": cards,
        "{{FLEET_TOPOLOGY}}": topo,
        "{{FLEET_STREAM_ROWS}}": stream_rows,
        "{{FLEET_STREAM_JS}}": stream_js,
        "{{TOTAL_AGENTS}}": str(len(fleet)),
        "{{HEALTHY}}": str(healthy),
        "{{HEALTHY_CLASS}}": "good" if healthy == len(fleet) else "warn",
        "{{HOSTS}}": str(len(hosts)),
        "{{GENERATED_AT}}": generated,
    }
    out = TEMPLATE.read_text()
    for k, v in values.items():
        out = out.replace(k, v)
    OUT_HTML.write_text(out)

    OUT_JSON.write_text(json.dumps({
        "generated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "healthy": healthy,
        "total": len(fleet),
        "agents": fleet,
    }, indent=2) + "\n")

    print(f"wrote {OUT_HTML} and {OUT_JSON} ({healthy}/{len(fleet)} healthy)")


if __name__ == "__main__":
    main()
