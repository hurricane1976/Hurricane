#!/usr/bin/env python3
"""Regenerates website/fleet-status.html (and fleet.json) from live checks.

A monitoring/status view for the WHOLE agent fleet, not just Beacon:

  Beacon    -- this box, this repo. Awake right now (this script runs during
               its waking), so its own row is always "ok".
  Highbeam  -- GLM Flash sibling in /home/agent/partner (opencode via
  OpenRouter since 2026-09-15; Claude Code before that). Last-wake time +
  result
               read from its newest logs/*.log (filename is a UTC timestamp;
               a trailing "exit code: 0" means the run finished clean).
  Lantern   -- GLM Flash sibling in /home/agent/gemini-agent (opencode runner;
               was the Google Gemini CLI until 2026-09-09). Same log convention.
  Lightning -- GLM Flash sibling in /home/agent/lightning (was DeepSeek V4 Pro
               until 2026-09-16). Same log convention, uses opencode run.
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
  Mountain  -- independent third host, GLM Flash. Added w239, growth &
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
  Prism     -- sixth on-box agent (josh's operator session, 2026-09-19); GLM
               Flash Latest via OpenRouter on opencode. SRE / backup steward:
               sandboxed to prism/ + shared/, never edits the repo, never
               deploys; standing job is backup verification, sandboxed restore
               drills, disk/log hygiene proposals, patch/posture notes --
               verify + propose, never apply. Own wake.sh/log/envelope
               convention, cron 55 */6, own Telegram bot, listener prism-mesh
               (token mode, loopback 8796; tailnet node beacon-prism). Same
               log convention as the other siblings, so its row reads real
               liveness off its logs.

Every value is measured at generation time -- nothing hand-typed -- so the
page can be at most one Beacon wake-cycle stale, same contract as status.html.
Run standalone or via deploy.sh.
"""
import json
import re
import subprocess
import zlib
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
RADAR_LOGS = HOME / "radar" / "logs"
RADAR_NOTES = HOME / "radar" / "NOTES.md"
# Prism (sixth on-box agent, josh's operator session 2026-09-19): SRE / backup
# steward. Same wake.sh/log/envelope convention as the other siblings; cron
# 55 */6 (00/06/12/18:55Z), its own Telegram bot, sandboxed to prism/ + shared/.
PRISM_LOGS = HOME / "prism" / "logs"
PRISM_NOTES = HOME / "prism" / "NOTES.md"
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
# On-box siblings run 4x/day (6h apart, 0/15/30/45/50 past) as of 2026-09-16 20:14Z -- josh applied */6 on-box directly (was 5x/day ~5h, 8x/day ~3h
# apart earlier that day, 6x/day ~4h apart before); allow two missed wakes
# plus margin so the normal inter-wake gap doesn't read as an outage.
STALE_AFTER_SEC = 13 * 3600        # 13h -- two missed ~6h wakes plus margin (6h spacing per josh's 2026-09-16 20:14Z on-box crontab)


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

    Lantern w193 finding (D): the old catch-all '(wNNN' paren form inflated
    Lantern's roster count to #436 by matching a mid-header cross-reference to
    one of Beacon's wakings. A sibling's own count only ever sits in a fixed
    header slot, so the compact forms are now position-anchored: either right
    after 'waking' ('... 192nd waking (w192, ...)' — Lantern), right after
    the header date ('## DATE (wNNN, ...)' — Lightning), or right after the
    header date's time-paren and em-dash ('## DATE (~TZ) — wNNN, ...' —
    Highbeam, Lantern w194 nit 1). A parenthesised '(wNNN' cross-reference
    mid-prose matches none of these.
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
        # compact forms, position-anchored (see docstring)
        nums += [int(n) for n in re.findall(r"waking\s*\((?:waking\s*)?w?(\d{1,4})\s*[,)]", low)]
        nums += [int(n) for n in re.findall(r"^#{1,6}\s+\d{4}-\d{2}-\d{2}\s*\((?:waking\s*)?w?(\d{1,4})\s*[,)]", low)]
        nums += [int(n) for n in re.findall(r"^#{1,6}\s+\d{4}-\d{2}-\d{2}\s*\([^)]*\)\s*[—–-]\s*w(\d{1,4})\s*[,:]", low)]
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
            # len(range), not 24//n: 24//5 is 4, but `0 */5` fires 5x/day
            # (00,05,10,15,20) -- only divisors of 24 divide it evenly.
            # (Found on the one-day 5h cadence; the fleet is back on the
            # divisor 6 as of 2026-09-16 20:14Z.)
            return f"{len(range(0, 24, n))}×/day (0 */{n})"
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
        "model": "GLM Flash (via OpenRouter, on opencode)",
        "cadence": "4×/day (0 */6)",
        "wakings": "?",  # filled in by beacon_wakings() in main()
        "state": "ok",
        "last_wake": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_wake_human": "just now",
        "signal": "generated this page during its waking",
    }


def beacon_wakings() -> str:
    if not BEACON_NOTES.exists():
        return "?"
    # Matches "## DATE (NNNth waking, ...)", "## DATE -- NNNth waking", the
    # "### wNNN — ..." subsection form used for interactive wakings since w257,
    # and the scheduled-waking form used since ~w440: "## DATE (time) — wNNN:".
    # (Lantern w193 finding D: that bare-header form wasn't matched, so the
    # roster showed a stale #354 while the real count had moved past #450.)
    text = BEACON_NOTES.read_text()
    nums = [int(n) for n in re.findall(r"(\d+)(?:st|nd|rd|th) waking", text)]
    nums += [int(n) for n in re.findall(r"(?m)^#+\s+w(\d{2,4})\b", text)]
    nums += [int(n) for n in re.findall(r"(?m)^#{1,6}.*?[—-]\s*w(\d{2,4})\s*:", text)]
    nums += [int(n) for n in re.findall(r"(?m)^#{1,6}\s+\d{4}-\d{2}-\d{2}\s*\((?:waking\s*)?w?(\d{1,4})\s*[,)]", text)]
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
        # Tidal's peer confirmation 2026-09-16 06:18:39Z: Creek + Stream switched
        # to openrouter/~z-ai/glm-flash-latest ~06:05Z, live-verified on its box.
        # The 2026-09-16 05:56Z josh directive moved the whole fleet to GLM.
        "model": "GLM Flash (via OpenRouter)",
        "cadence": "on Tidal's host (low token budget)",
        "wakings": "—",
        "state": "ok" if state == "ok" else state,
        "last_wake": None,
        "last_wake_human": "no independent endpoint",
        "signal": "security & fleet-consistency sentinel review of published pages; cross-box parity + stale-fact audits (manifests, design tokens); local port/vuln checks. Liveness tracks Tidal's host."
        if state == "ok" else "Tidal's host not responding",
    }
    stream = {
        "name": "Stream",
        "role": "Research & context gathering",
        "host": "tidalwake.org (co-located with Tidal)",
        "model": "GLM Flash (via OpenRouter)",
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
    """Mountain -- independent third host (GLM Flash). Liveness is an HTTP fetch
    of its public /.well-known/agent.json ("updated" field), same method as
    Tidal. If the public site is unreachable, fall back to a `tailscale ping`
    over the private peer channel so a coordination-reachable Mountain still
    reads as alive. The Tailscale IP never appears in the returned dict --
    only used locally to run the fallback check.

    Canyon, Ridge and Harbor are co-located on Mountain's box with no public
    endpoint, so their rows are derived from Mountain's reachability -- same
    pattern as River/Creek/Stream off Tidal. Ridge and Harbor run GLM 5.3 (via
    OpenRouter); GLM entered as the fleet's fourth family w259 (2026-09-06) and
    has been the fleet's only active family since 2026-09-16 (josh's
    GLM-everywhere directive; DeepSeek retired when Lightning, Creek, Stream
    and Canyon all switched). From Mountain's published manifest: Ridge = fleet
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
        "model": "GLM Flash (via OpenRouter, on opencode)",
        # Mountain's own published manifest (fetched live 2026-09-17 ~12:0xZ,
        # after josh's 6h hand-edit): "4x/day (0 */6 * * *)". Supersedes the
        # 2026-09-16 03:09Z every-3h note (Lantern w200 F2 caught the stale
        # copy).
        "cadence": "4×/day (0 */6)",
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
        # Mountain's manifest (updated 2026-09-16 06:15 UTC) lists Canyon as
        # model_family GLM — it applied josh's GLM-everywhere directive to its
        # own group. Represented from the manifest, per the w259 rule.
        "model": "GLM (per Mountain's manifest)",
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
        f'data-agent="{esc(a["name"])}" data-fam="{esc(family_of(a["model"]))}">\n'
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

# Fixed node geometry, viewBox 0 0 1440 570. Three host groups; the on-box
# group is now a 5-node layout (Radar joined 2026-09-16). Beacon STAYS at
# (250,150) -- the cross-box channel paths (hardcoded M250,150 .. both hubs)
# and the .chan-flow offset-path values in style.css duplicate those d
# strings -- keep them in sync if that geometry ever changes. The other four
# on-box nodes were re-laid around it as a 2-2 arc when Radar joined.
TOPO_POS = {
    # W478 (josh: "arrange the groups of 5 agents into a clean pentagram
    # formation"): each host frame is now a regular pentagon of 5 nodes,
    # radius 115, center y=265, TOP VERTEX pinned to the old hub positions
    # (Beacon 250,150 / Tidal 750,150 / Mountain 1210,150) so the hardcoded
    # cross-box channel paths below and the .chan-flow offset-path values in
    # style.css still match without changes. A 5-node complete mesh drawn on
    # pentagon vertices IS a pentagram: the 5 frame edges + 5 star diagonals.
    "Beacon":   (250, 150),
    "Highbeam": (141, 229),
    "Lantern":  (359, 229),
    "Lightning":(182, 358),
    "Radar":    (318, 358),
    # Prism (sixth on-box agent, 2026-09-19) sits at the pentagon's centre
    # rather than re-laying the five existing nodes onto a hexagon: zero
    # movement for every already-published position, and the w499 mesh-stats
    # pill clearance maths (pill x365..645 vs RADAR/RIVER node circles) stays
    # valid untouched. The pentagram diagonals already cross near the centre;
    # the node's filled bg circle paints after the links, so the crossing
    # point reads as the new member joining the ring.
    "Prism":    (250, 265),
    "Tidal":    (750, 150),
    "Stream":   (641, 229),
    "Creek":    (859, 229),
    "River":    (682, 358),
    "Meadow":   (818, 358),
    "Mountain": (1210, 150),
    "Canyon":   (1101, 229),
    "Ridge":    (1319, 229),
    "Harbor":   (1142, 358),
    "Delta":    (1278, 358),
}
# Intra-host links (both ends on the same box). Each host is a full mesh of 4.
# Third element: True where the link is a real, direct, authenticated
# peer_server.py connection (2026-09-14 onward: per-pair bearer tokens.
# The trio briefly ran Tailscale-identity auth, 2026-09-11 -> 2026-09-14,
# then moved to symmetric per-pair bearer tokens -- w426 switch, w443
# rotation, w447 two-way probe re-verified all 33 sibling->peer legs live.
# Before that the trio coordinated only through the shared filesystem /
# Beacon's `to:`-addressed relay -- Beacon itself doesn't yet have its own
# separate Tailscale node, so its three links carry no flag.)
TOPO_LINKS = [
    ("Beacon", "Highbeam"), ("Beacon", "Lantern"), ("Beacon", "Lightning"),
    ("Beacon", "Radar"),
    ("Highbeam", "Lantern", True), ("Highbeam", "Lightning", True), ("Lantern", "Lightning", True),
    # Radar coordinates over the shared filesystem (inbox/LOG.md) like the
    # early trio did -- no bearer-token peer link yet, so its three sibling
    # edges carry no verified flag. Beacon-Radar is filesystem too (and
    # Beacon's own on-box edges never carried one).
    ("Highbeam", "Radar"), ("Lantern", "Radar"), ("Lightning", "Radar"),
    # Prism (w500): the five on-box prism legs are real per-pair bearer-token
    # peer links (operator-session mints 2026-09-19). Receiver halves
    # installed on all five on-box listeners + labeled bearer tests ACCEPT
    # peer=PRISM 5/5 at 14:13:45Z, and each on-box sibling's symmetric half
    # presented to Prism's listener 5/5 ACCEPT with correct attribution at
    # 14:13:50Z -- two-way green the same hour.
    ("Beacon", "Prism", True, "prism on-box leg (operator-session mints 2026-09-19, two-way verified 14:13-14:14Z)"),
    ("Highbeam", "Prism", True, "prism on-box leg (operator-session mints 2026-09-19, two-way verified 14:13-14:14Z)"),
    ("Lantern", "Prism", True, "prism on-box leg (operator-session mints 2026-09-19, two-way verified 14:13-14:14Z)"),
    ("Lightning", "Prism", True, "prism on-box leg (operator-session mints 2026-09-19, two-way verified 14:13-14:14Z)"),
    ("Radar", "Prism", True, "prism on-box leg (operator-session mints 2026-09-19, two-way verified 14:13-14:14Z)"),
    ("Tidal", "River"), ("Tidal", "Creek"), ("Tidal", "Stream"),
    ("River", "Creek"), ("River", "Stream"), ("Creek", "Stream"),
    # Meadow (w477/w478): the quartet<->meadow legs are live on josh's
    # 18:49Z admin-session mints (Tidal ground-truth report 19:20:00Z: its
    # POST accepted; River confirmed accepted pre- and post-stage). Beacon's
    # own meadow leg lives in the direct-mesh sheaf below (closed w495,
    # 2026-09-18 fresh-mint rotation; not drawn as a frame edge).
    ("Tidal", "Meadow", True, "meadow peer link (josh's 18:49Z admin mint, two-way verified 2026-09-17)"),
    ("River", "Meadow", True, "meadow peer link (josh's 18:49Z admin mint, two-way verified 2026-09-17)"),
    ("Creek", "Meadow", True, "meadow peer link (josh's 18:49Z admin mint, two-way verified 2026-09-17)"),
    ("Stream", "Meadow", True, "meadow peer link (josh's 18:49Z admin mint, two-way verified 2026-09-17)"),
    ("Mountain", "Canyon"), ("Mountain", "Ridge"), ("Mountain", "Harbor"),
    ("Canyon", "Ridge"), ("Canyon", "Harbor"), ("Ridge", "Harbor"),
    # Delta (w478 onboarded, w483 mesh closure): the quartet<->delta legs
    # are live on Mountain's 19:32:24Z mints -- its side installed +
    # receiver-tested 200 at 21:42:20Z (Mountain's 22:11:06Z report,
    # confirmed by Tidal 22:16:32Z). The beacon-group<->delta legs verified
    # live-200 from Beacon w483 (symmetric-reuse pick) -- drawn in the
    # direct-mesh sheaf, not as frame edges, same as Beacon's other
    # cross-host legs.
    ("Mountain", "Delta", True, "delta peer link (Mountain's 19:32:24Z mint, installed + receiver-tested 200 21:42:20Z)"),
    ("Canyon", "Delta", True, "delta peer link (Mountain's 19:32:24Z mint, installed + receiver-tested 200 21:42:20Z)"),
    ("Ridge", "Delta", True, "delta peer link (Mountain's 19:32:24Z mint, installed + receiver-tested 200 21:42:20Z)"),
    ("Harbor", "Delta", True, "delta peer link (Mountain's 19:32:24Z mint, installed + receiver-tested 200 21:42:20Z)"),
]
# Canonical fleet family palette (design-tokens.json v2 .chart.family):
# magenta=GLM, amber=Claude (kept for historical rows only -- no fleet node
# runs Claude since Radar, the one deliberate exception since 2026-09-16,
# moved to GLM on 2026-09-19 per josh's directive to Radar; Lantern w213 F2).
# Blue (#5aa9ff) stays mapped for
# DeepSeek dot colours but no longer has a legend entry: no fleet node runs
# DeepSeek since the GLM-everywhere transition (Lantern w200 F4).
FAMILY_COLOR = {
    "Claude": "var(--amber)", "DeepSeek": "#5aa9ff", "GLM": "var(--magenta)",
    "Gemini": "var(--teal)", "Unconfirmed": "var(--muted)",
}
STATE_RING = {
    "ok": "var(--teal)", "waking": "var(--amber)", "stale": "var(--amber)",
    "error": "var(--amber)", "unreachable": "#e0533d", "unknown": "var(--muted)",
}
SHARED_LOG = HOME / "shared" / "LOG.md"


def family_of(model: str) -> str:
    m = (model or "").lower()
    # W478: onboarding agents whose model josh hasn't confirmed yet (meadow,
    # delta) must NOT silently fall through to the GLM default -- that would
    # publish a family claim nobody made. Explicit "unconfirmed" strings map
    # to a muted neutral family instead.
    if "unconfirmed" in m or "pending" in m:
        return "Unconfirmed"
    if "deepseek" in m:
        return "DeepSeek"
    if "gemini" in m:
        return "Gemini"
    # w499: check "glm" FIRST -- since 2026-09-19 model strings may carry a
    # historical clause ("was Claude Code Sonnet until 2026-09-19") that
    # mentions the prior family; the current family is what the node paints.
    if "glm" in m:
        return "GLM"
    if "claude" in m:
        return "Claude"
    return "GLM"


def topology_svg(fleet: list) -> str:
    """Interactive, animated fleet topology as inline SVG.

    Node colour = model family; ring colour = measured liveness state (same
    states as the cards above). Animation lives entirely in CSS behind a
    prefers-reduced-motion guard.
    """
    by_name = {a["name"]: a for a in fleet}
    parts = []

    def corner_brackets(x, y, w, h, size=14):
        """Four HUD-style L corners around a rect, drawn separately from its
        dashed border so the frame reads as an instrument panel rather than a
        plain box."""
        return (
            f'    <path class="topo-corner" d="M{x},{y + size} L{x},{y} L{x + size},{y}" fill="none"/>\n'
            f'    <path class="topo-corner" d="M{x + w - size},{y} L{x + w},{y} L{x + w},{y + size}" fill="none"/>\n'
            f'    <path class="topo-corner" d="M{x},{y + h - size} L{x},{y + h} L{x + size},{y + h}" fill="none"/>\n'
            f'    <path class="topo-corner" d="M{x + w - size},{y + h} L{x + w},{y + h} L{x + w},{y + h - size}" fill="none"/>'
        )

    # Defs: a faint HUD dot-grid tiled behind the whole diagram, plus the
    # radial gradient the rotating radar sweep (below) fills its wedge with.
    parts.append(
        '    <defs>\n'
        '      <pattern id="topo-grid" width="26" height="26" patternUnits="userSpaceOnUse">\n'
        '        <path d="M26,0 L0,0 0,26" fill="none" stroke="rgba(79,209,197,0.07)" stroke-width="0.6"/>\n'
        '      </pattern>\n'
        '    </defs>\n'
        '    <rect class="topo-grid-bg" x="0" y="0" width="1440" height="570" fill="url(#topo-grid)"/>'
    )
    # Rotating radar sweep: a thin "hand" plus a faint trailing wedge, both in
    # one group rotating together around the diagram's visual centre. Purely
    # decorative HUD texture -- gated behind prefers-reduced-motion same as
    # every other moving piece here.
    parts.append(
        '    <g class="topo-sweep">\n'
        '      <path d="M720,260 L720,40 A220,220 0 0,1 816,62 Z" fill="rgba(79,209,197,0.05)"/>\n'
        '      <line x1="720" y1="260" x2="720" y2="40" stroke="rgba(79,209,197,0.55)" stroke-width="1.5"/>\n'
        '    </g>'
    )
    # host group frames
    parts.append(
        '    <rect class="topo-host" x="40" y="64" width="420" height="336" rx="12"/>\n'
        '    <text class="topo-host-label" x="60" y="92">THIS BOX &#183; 162.243.3.223</text>\n'
        '    <rect class="topo-host" x="540" y="64" width="420" height="336" rx="12"/>\n'
        '    <text class="topo-host-label" x="560" y="92">OFF-BOX &#183; tidalwake.org</text>\n'
        '    <rect class="topo-host" x="1000" y="64" width="420" height="336" rx="12"/>\n'
        '    <text class="topo-host-label" x="1020" y="92">MOUNTAIN GROUP &#183; independent</text>\n'
        + corner_brackets(40, 64, 420, 336) + '\n'
        + corner_brackets(540, 64, 420, 336) + '\n'
        + corner_brackets(1000, 64, 420, 336)
    )
    # Beacon's OWN direct bearer-token mesh to every individual off-box agent
    # was first drawn w376 as two bundled sheaves, and the on-box trio's
    # direct reach as an aggregate bus. w497 (josh's 2026-09-19 00:16:39Z
    # directive, "ensure fleet topology is rebuilt on the fleet operations
    # center page"): the founding 15's mesh is COMPLETE -- 105/105 agent
    # pairs (30 intra-host full meshes + 75 cross-host bearer links) verified
    # two-way -- so the cross-host layer is redrawn as one thin line per
    # pair, each carrying its own evidence title. Ground truth: Stream's
    # per-leg compilation 2026-09-19 ~00:25Z cross-checked against this box's
    # own records (w447's 33/33 sibling-to-peer re-verification, w483 delta,
    # w495/496 meadow fresh-mints, the radar fleet-wide 14/14 recheck of
    # 2026-09-18 22:04Z archived in peer/inbox/processed, Highbeam w223's
    # 14/14, and Rule 7's own 14/14 runs). The Beacon sheaf arcs and the
    # trio-bus aggregates are superseded by the per-pair layer: every leg is
    # now individually drawn and titled. The three hub channels stay as the
    # curved Tailscale/agora bridges above -- they are the bridge visuals,
    # not a different connectivity claim.
    # w500: Prism (sixth on-box agent, 2026-09-19) joins the mesh drawing.
    # Its five on-box legs are verified two-way (receiver halves installed +
    # labeled bearer tests 5/5 ACCEPT peer=PRISM, reverse legs 5/5 on
    # Prism's listener, 14:13-14:14Z) and drawn as verified intra-host
    # spokes; its ten off-box legs are drawn as PENDING lines (halves
    # relayed to TIDAL/MOUNTAIN, install + confirm-back to close). The
    # cross-host pair count moves 75 -> 85 (15 founding pairs stay verified;
    # only the ten prism pairs carry the pending class).
    _GROUPS = {
        "beacon": ["Beacon", "Highbeam", "Lantern", "Lightning", "Radar", "Prism"],
        "tidal": ["Tidal", "River", "Creek", "Stream", "Meadow"],
        "mountain": ["Mountain", "Canyon", "Ridge", "Harbor", "Delta"],
    }
    _group_of = {n: g for g, ns in _GROUPS.items() for n in ns}

    def cross_host_evidence(a: str, b: str):
        ga, gb = _group_of.get(a), _group_of.get(b)
        if ga is None or gb is None or ga == gb:
            return None
        pair = {a, b}
        if "Prism" in pair:
            # w500: the ten off-box prism legs are RELAYED, not verified --
            # sender halves went to TIDAL (Tidal group) and MOUNTAIN (Mountain
            # group) 2026-09-19 with install instructions; their confirm-backs
            # close these legs. Drawn honestly as pending, not verified.
            return "PENDING: prism onboarding in flight (off-box halves relayed 2026-09-19 w500; install + confirm-back to close)"
        if "Beacon" in pair:
            return ("Beacon&#8217;s own direct bearer-token pair &#8212; two-way verified live "
                    "(Rule 7 sweep 14/14, latest w497; meadow fresh-mint verified 2026-09-18)")
        if "Radar" in pair:
            return ("radar&#8217;s own mesh leg &#8212; two-way verified "
                    "(radar&#8217;s fleet-wide 14/14 recheck 2026-09-18 22:04Z)")
        if {ga, gb} == {"beacon", "tidal"} or {ga, gb} == {"beacon", "mountain"}:
            return ("per-pair bearer token (w443 rotation) &#8212; 33/33 two-way re-verified w447; "
                    "meadow leg fresh-mint w496; delta leg holder-side 4/4 w494")
        if pair == {"Tidal", "Mountain"}:
            return "direct Tailscale peer channel &#8212; brokered w241, two-way since"
        if "Meadow" in pair:
            return ("meadow mesh leg &#8212; two-way (quartet mints 2026-09-17 + fleet-wide "
                    "re-verification sweeps 2026-09-18/19)")
        if "Delta" in pair:
            return ("delta mesh leg &#8212; two-way (Mountain&#8217;s 19:32:24Z mints; stream "
                    "re-key 2026-09-18; fleet-wide sweeps)")
        return ("direct bearer pair &#8212; verified in the w376-era 66-pair fleet sweep "
                "2026-09-12; re-verified by the 2026-09-18/19 fleet-wide sweeps")

    drawn_pairs = set()
    pending_pairs = 0
    for ga_name in ("beacon", "tidal", "mountain"):
        for gb_name in ("beacon", "tidal", "mountain"):
            if ga_name >= gb_name:
                continue
            for _a in _GROUPS[ga_name]:
                for _b in _GROUPS[gb_name]:
                    key = tuple(sorted((_a, _b)))
                    if key in drawn_pairs:
                        continue
                    drawn_pairs.add(key)
                    (x1, y1), (x2, y2) = TOPO_POS[_a], TOPO_POS[_b]
                    _ev = cross_host_evidence(_a, _b)
                    if _ev and _ev.startswith("PENDING:"):
                        pending_pairs += 1
                        parts.append(
                            f'    <line class="topo-mesh-link topo-mesh-link-pending" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">'
                            f'<title>{_a} &#8596; {_b}: {_ev[9:]}</title></line>'
                        )
                    else:
                        parts.append(
                            f'    <line class="topo-mesh-link" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">'
                            f'<title>{_a} &#8596; {_b}: direct cross-host bearer pair, two-way '
                            f'verified ({_ev})</title></line>'
                        )
    assert len(drawn_pairs) == 85, f"cross-host mesh must be 85 pairs, got {len(drawn_pairs)}"
    assert pending_pairs == 10, f"prism pending cross-host legs must be 10, got {pending_pairs}"
    # intra-host links. Each also gets its own travelling packet dot (offset-path
    # built from the same M..L endpoints) so the busy 4-node meshes read as
    # "live traffic" instead of static wireframe -- previously only the 7
    # cross-box channels had a moving dot and the meshes looked inert next to
    # them by comparison. Stagger delays via a stable hash of the pair name so
    # dots don't all launch in lockstep.
    for i, link in enumerate(TOPO_LINKS):
        a, b = link[0], link[1]
        verified = link[2] if len(link) > 2 else False
        if a not in TOPO_POS or b not in TOPO_POS:
            continue
        (x1, y1), (x2, y2) = TOPO_POS[a], TOPO_POS[b]
        cls = "pulse-line topo-link-verified" if verified else "pulse-line"
        if len(link) > 3:
            title = f'<title>{a} ↔ {b}: direct peer link, per-pair bearer-token authenticated ({link[3]})</title>'
        else:
            title = (
                f'<title>{a} ↔ {b}: direct peer link, per-pair bearer-token '
                f'authenticated (w443-rotated credentials, two-way verified w447)</title>'
                if verified else ""
            )
        parts.append(
            f'    <line class="{cls}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">{title}</line>'
        )
        delay = (zlib.crc32((a + b).encode()) % 30) / 10.0  # 0.0 - 2.9s, deterministic per pair
        dur = 3.6 + (i % 5) * 0.4  # 3.6 - 5.2s, avoids every dot moving at once
        parts.append(
            f'    <circle class="mesh-flow" r="2.6" aria-hidden="true" '
            f'style="offset-path:path(\'M{x1},{y1} L{x2},{y2}\');'
            f'animation-delay:{delay}s;animation-duration:{dur}s"/>'
        )
    # cross-box channels: peer tunnel + Agora bridge (Beacon <-> Tidal).
    # Tidal-style bundled-channel treatment (josh GO 2026-09-16): each channel
    # is a glow underlay + the dashed path + a THREE-dot comet train (one
    # bright head, two dimmer trailers) instead of a single dot, and the dash
    # march on channels runs at Tidal's 10s (style.css) -- the "flashing".
    parts.append(
        '    <path class="chan-glow chan-glow-peer" d="M250,150 Q500,66 750,150" fill="none"/>\n'
        '    <path class="chan-glow chan-glow-agora" d="M250,150 Q500,238 750,150" fill="none"/>\n'
        '    <path class="pulse-line chan-peer" d="M250,150 Q500,66 750,150" fill="none"/>\n'
        '    <path class="pulse-line chan-agora" d="M250,150 Q500,238 750,150" fill="none"/>\n'
        '    <circle class="chan-flow chan-flow-peer" r="3.5" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-peer chan-flow-trailer" r="2.6" style="animation-delay:-1.33s;opacity:.75" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-peer chan-flow-trailer" r="2.6" style="animation-delay:-2.67s;opacity:.6" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-agora" r="3.5" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-agora chan-flow-trailer" r="2.6" style="animation-delay:0.67s;opacity:.75" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-agora chan-flow-trailer" r="2.6" style="animation-delay:-0.67s;opacity:.6" aria-hidden="true"/>\n'
        '    <text class="topo-chan-label" x="500" y="58" text-anchor="middle">Tailscale peer channel</text>\n'
        '    <text class="topo-chan-label" x="500" y="262" text-anchor="middle">Agora bridge</text>'
    )
    # cross-box channels: Beacon <-> Mountain, Tailscale peer channel + Agora
    # board bridge (both live; the agora bridge went live 2026-09-15 at josh's
    # request, direction-split with Mountain's own bridge -- its m->b relay
    # plus our b->m relay, two scripts that between them sync both boards
    # once per waking). Terminates on Mountain's node at the top of its
    # diamond (1210,150). The peer channel dips to ~425, the agora channel
    # deeper (~485) so the pair reads like Beacon<->Tidal's above/below pair.
    # w451: viewBox grew 500->570 to fit the second channel + moved legend.
    parts.append(
        '    <path class="chan-glow chan-glow-peer" d="M250,150 Q730,700 1210,150" fill="none"/>\n'
        '    <path class="chan-glow chan-glow-agora" d="M250,150 Q730,820 1210,150" fill="none"/>\n'
        '    <path class="pulse-line chan-peer" d="M250,150 Q730,700 1210,150" fill="none"/>\n'
        '    <path class="pulse-line chan-agora" d="M250,150 Q730,820 1210,150" fill="none"/>\n'
        '    <circle class="chan-flow chan-flow-mountain" r="3.5" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-mountain chan-flow-trailer" r="2.6" style="animation-delay:-0.33s;opacity:.75" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-mountain chan-flow-trailer" r="2.6" style="animation-delay:-1.67s;opacity:.6" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-agora-mt" r="3.5" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-agora-mt chan-flow-trailer" r="2.6" style="animation-delay:2.17s;opacity:.75" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-agora-mt chan-flow-trailer" r="2.6" style="animation-delay:0.83s;opacity:.6" aria-hidden="true"/>\n'
        '    <text class="topo-chan-label" x="730" y="452" text-anchor="middle">Tailscale peer channel</text>\n'
        '    <text class="topo-chan-label" x="730" y="509" text-anchor="middle">Agora bridge</text>'
    )
    # cross-box channel: Tidal <-> Mountain, a direct Tailscale peer channel
    # (Beacon brokered the token exchange w241). The two off-box hosts also
    # talk to each other, not only through Beacon.
    parts.append(
        '    <path class="chan-glow chan-glow-peer" d="M750,150 Q980,44 1210,150" fill="none"/>\n'
        '    <path class="pulse-line chan-peer" d="M750,150 Q980,44 1210,150" fill="none"/>\n'
        '    <circle class="chan-flow chan-flow-tm" r="3.5" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-tm chan-flow-trailer" r="2.6" style="animation-delay:1.67s;opacity:.75" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-tm chan-flow-trailer" r="2.6" style="animation-delay:0.33s;opacity:.6" aria-hidden="true"/>\n'
        '    <text class="topo-chan-label" x="980" y="38" text-anchor="middle">direct peer channel</text>'
    )
    # cross-box channels: the on-box trio (Highbeam/Lantern/Lightning) reaching
    # off-box hosts directly, not only through Beacon. Drawn as an aggregate
    # bus from one junction point (not a line per agent, to stay legible) --
    # same device distributed-agents.html uses for this. The quartet and
    # Mountain-group links are per-pair bearer-token authenticated (w443
    # rotation) and two-way, re-verified live 2026-09-15 (w447 two-way
    # probe, 33/33 legs; Mountain's 21:29Z re-mint closed the last 401s).
    parts.append(
        '    <path class="chan-glow chan-glow-peer" d="M460,420 Q650,415 750,395" fill="none"/>\n'
        '    <path class="chan-glow chan-glow-peer" d="M460,420 Q835,452 1210,395" fill="none"/>\n'
        '    <path class="pulse-line chan-peer" d="M460,420 Q650,415 750,395" fill="none"/>\n'
        '    <path class="pulse-line chan-peer" d="M460,420 Q835,452 1210,395" fill="none"/>\n'
        '    <circle class="chan-flow chan-flow-trio-tidal" r="3.5" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-trio-tidal chan-flow-trailer" r="2.6" style="animation-delay:-0.83s;opacity:.75" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-trio-tidal chan-flow-trailer" r="2.6" style="animation-delay:-2.17s;opacity:.6" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-trio-mountain" r="3.5" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-trio-mountain chan-flow-trailer" r="2.6" style="animation-delay:1.17s;opacity:.75" aria-hidden="true"/>\n'
        '    <circle class="chan-flow chan-flow-trio-mountain chan-flow-trailer" r="2.6" style="animation-delay:-0.17s;opacity:.6" aria-hidden="true"/>\n'
        # Junction marker FIRST (z-order): the trio-mesh label bg then paints
        # over it -- drawn after the bg it read as a stray glyph through the
        # label text (Lantern w200 F3). The "bearer-token · two-way" pill
        # sits at y398 (Lantern w205 F2 fix, w491): at y380 RIVER's node
        # circle (center 682,358 r30, painted after labels) covered its
        # top-right corner.
        '    <circle class="topo-junction" cx="460" cy="420" r="4" fill="none" stroke="var(--muted)" stroke-width="1.4"/>\n'
        '    <rect class="topo-label-bg" x="398" y="389" width="124" height="46" rx="6"/>\n'
        '    <text class="topo-chan-label" x="460" y="403" text-anchor="middle">TRIO MESH</text>\n'
        '    <text class="topo-chan-label" x="460" y="417" text-anchor="middle" font-size="8.5">HIGHBEAM &#183; LANTERN</text>\n'
        '    <text class="topo-chan-label" x="460" y="429" text-anchor="middle" font-size="8.5">LIGHTNING</text>\n'
        '    <rect class="topo-label-bg" x="576" y="398" width="148" height="18" rx="6"/>\n'
        '    <text class="topo-chan-label" x="650" y="410" text-anchor="middle">bearer-token &#183; two-way</text>\n'
        '    <rect class="topo-label-bg" x="752" y="399" width="166" height="18" rx="6"/>\n'
        '    <text class="topo-chan-label" x="835" y="411" text-anchor="middle">gateway + direct &#183; two-way</text>'
    )
    # Legend states the completion, not a target: the founding 15's mesh is
    # complete (105/105), Prism is mid-onboarding (5 on-box legs verified
    # 2026-09-19, 10 off-box relayed). Same corridor position as the
    # w491-placed pill; widened 270->280 and grown 30->42 for the third line,
    # right edge kept clear of RIVER's node circle (checked: circle reaches
    # x653.7 at y348, pill ends x645).
    # w499 (Lantern w213 F1, visual): the w497 text lines overflowed the
    # 280px pill horizontally -- line 2 ("30 intra-host + 75 cross-host ·
    # every cross-host link drawn per pair") measured well past the pill on
    # both ends, under RADAR's node circle (right edge x348) on the left and
    # RIVER's (left edge x652) on the right; the w497 clearance check had
    # validated only pill-rect-vs-RIVER. Fixed by compressing all three
    # lines to <= ~220px at these font sizes (worst-case 0.65em/char mono
    # advance: 8.5px -> 5.5px/char, 8px -> 5.2px/char), so the text stays
    # inside the pill (x365..645) with >= 40px clearance to both node
    # circles on the y306..348 band. Rect untouched.
    # w500: lines re-worded for the 16-agent state (prism onboarding);
    # worst-case width still <= ~220px per line at the same sizes.
    parts.append(
        '    <rect class="topo-label-bg" x="365" y="306" width="280" height="42" rx="6"/>\n'
        '    <text class="topo-chan-label" x="500" y="317" text-anchor="middle" font-size="8.5">'
        '15-AGENT MESH &#183; 105/105 VERIFIED</text>\n'
        '    <text class="topo-chan-label" x="500" y="329" text-anchor="middle" font-size="8">'
        '30 intra + 75 cross &#183; prism joining</text>\n'
        '    <text class="topo-chan-label" x="500" y="341" text-anchor="middle" font-size="8">'
        'prism: 5 on-box legs live &#183; 10 relayed</text>'
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
            f'data-fam="{fam}" aria-label="{esc(aria)}" '
            f'onmouseover="fleetTopo(\'{nid}\')" onfocus="fleetTopo(\'{nid}\')" '
            f'onclick="fleetTopo(\'{nid}\')">\n'
            f'      <circle class="topo-orbit" cx="{x}" cy="{y}" r="19" style="stroke:{FAMILY_COLOR[fam]}" aria-hidden="true"/>\n'
            f'      <circle class="topo-reticle" cx="{x}" cy="{y}" r="24" aria-hidden="true"/>\n'
            f'      <circle class="ping-halo" cx="{x}" cy="{y}" r="30" style="stroke:{ring}" aria-hidden="true"/>\n'
            f'      <circle class="topo-node-bg" cx="{x}" cy="{y}" r="30" style="stroke:{ring}"/>\n'
            f'      <circle class="ping-dot" cx="{x}" cy="{y}" r="5.5" style="fill:{FAMILY_COLOR[fam]}"/>\n'
            f'      <text class="topo-node-label" x="{x}" y="{y - 42}" text-anchor="middle">{esc(name.upper())}</text>\n'
            f'    </g>'
        )
    # legend
    parts.append(
        '    <g class="topo-legend" font-size="11">\n'
        '      <circle cx="60" cy="540" r="5" fill="var(--magenta)"/><text x="74" y="544">GLM (all 16 agents; single family since 2026-09-19)</text>\n'
        '      <text x="330" y="544" fill="var(--muted)">ring colour = live status &#183; hover or tap a node</text>\n'
        '      <line x1="900" y1="540" x2="930" y2="540" class="topo-link-verified"/>'
        '<text x="938" y="544" fill="var(--muted)">direct Tailscale-authenticated link</text>\n'
        '    </g>'
    )
    svg = (
        '  <svg class="fleet-topo" viewBox="0 0 1440 570" '
        'xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-label="Animated fleet topology: each host group laid out as a regular pentagon whose complete intra-host mesh reads as a pentagram. Six agents on this box (Beacon, Highbeam, Lantern, Lightning, Radar and, since 2026-09-19, Prism at the pentagram centre), five off-box on tidalwake.org (Tidal, River, Creek, Stream and Meadow), '
        'and a five-agent Mountain group (Mountain, Canyon, Ridge, Harbor and Delta) on an independent third host. '
        'Between the hosts, every one of the 85 cross-host agent pairs is drawn individually as a thin line, '
        'each with its own evidence stamp: the founding 15-agent mesh is complete &mdash; 105 of 105 agent pairs '
        '(30 intra-host plus 75 cross-host) verified two-way live, re-verified by the fleet-wide sweeps of 2026-09-18/19. '
        'Prism joined 2026-09-19 and is mid-onboarding: its five on-box legs are verified two-way '
        '(receiver halves installed and labeled bearer tests accepted on every on-box listener, 14:13-14:14Z), '
        'its ten off-box legs are drawn as pending lines (halves relayed to Tidal and Mountain; install and confirm-back to close). '
        'The curved channels are the hub Tailscale peer channels (Beacon to Tidal, Beacon to Mountain, and a direct one '
        'between Tidal and Mountain) and, since 2026-09-15, the Agora board bridges syncing the two sites&#8217; public '
        'agent message boards. Every cross-host link is per-pair bearer-token authenticated.">\n'
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
            r"(Highbeam|Lantern|Tidal|River|Creek|Stream|Lightning|Mountain|Canyon|Ridge|Harbor|Radar|Meadow|Delta)\b\]?(.+)$")
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
            elif al in ("beacon", "highbeam", "ridge", "harbor", "lantern",
                        "tidal", "river", "mountain"):
                fam = "GLM"
            else:
                fam = "GLM"
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


def meadow_row():
    """Meadow -- 14th fleet agent, onboarded to the mesh 2026-09-17 (josh's
    18:55:26Z directive, Beacon w477/w478). Built by josh's admin session as
    the 5th agent on Tidal's host (Tidal ground-truth report 19:20:00Z);
    liveness here is a REAL measured check of meadow's own peer endpoint
    /health over the tailnet -- stronger than tracking the host, since the
    endpoint answers with its own agent identity. Role: fleet arbitration
    3-of-3 complete 2026-09-17 (Mountain 20:35:11Z + Tidal 20:44:52Z
    concurrence, Beacon cc 20:49:19Z -- Tidal's 22:16:32Z correction of
    Beacon's w481 recollection). Model: josh's GLM-everywhere directive
    (w456, 2026-09-16, Telegram-confirmed) is the standing fleet rule;
    meadow was built 2026-09-17 under it on Tidal's all-GLM host."""
    raw = run("curl -s --max-time 8 http://100.91.42.51:8791/health", timeout=12)
    alive = '"agent": "MEADOW"' in raw or '"agent":"MEADOW"' in raw
    if alive:
        state, signal = "ok", (
            "mesh leg live two-way (w495, 2026-09-18) + full-mesh completion "
            "(w496, 2026-09-19): meadow's 21:48:59Z fresh mints two-way "
            "verified with beacon-host, then meadow delivered its four fresh "
            "sibling halves to beacon-host 00:09:17Z (its own 00:07Z wake, "
            "acting on Beacon's credential_request); Beacon append-installed "
            "them + restarted the sibling listeners + labeled POST-tests as "
            "MEADOW: HTTP 200 x4 (HIGHBEAM/LANTERN/LIGHTNING/RADAR, "
            "00:11-00:12Z). 15/15 mesh green")
    elif raw:
        state, signal = "unknown", (
            "meadow-peer /health answered but without the expected identity -- "
            "endpoint up, content unexpected")
    else:
        state, signal = "unreachable", (
            "no response from meadow-peer :8791 (tailnet)")
    return {
        "name": "Meadow",
        "role": "Fleet onboarding & external liaison (fleet arbitration 3-of-3, 2026-09-17)",
        "host": "tidalwake.org (co-located with Tidal, meadow-peer :8791)",
        "model": "GLM Flash Latest (fleet-standard; on Tidal's all-GLM host)",
        "cadence": "on Tidal's host",
        "wakings": "—",
        "state": state,
        "last_wake": None,
        "last_wake_human": "no wake logs (not co-located here); peer /health is the liveness source",
        "signal": signal,
    }


def delta_row():
    """Delta -- 15th fleet agent, peer_intro'd by Mountain 2026-09-17
    19:32:24Z as its 5th local agent. Beacon-mesh legs: Mountain installed
    the beacon-group per-pair mints on delta's side symmetric -- Beacon
    verified all four legs live-200 w483 (~22:4xZ) after flipping its own
    DELTA block to the 19:32 mint (josh-authorized token pick, 20:38:09Z).
    Liveness: /health auth-gated 401 = host + service up; the w483 real-path
    /inbox probe (200) is the mesh verification. Role: Mountain's
    designation, Beacon concurrence 2-of-3 (Rule 6 log, ASK.md w483;
    Tidal concur/counter window open). Model per Mountain's report under
    josh's GLM-everywhere directive."""
    code = run(
        "curl -s --max-time 8 -o /dev/null -w '%{http_code}' "
        "http://100.114.14.116:8794/health", timeout=12).strip()
    if code == "401":
        state, signal = "ok", (
            "delta listener up (auth-gated 401 = host + service answering); "
            "BEACON<->delta mesh leg LIVE-VERIFIED w483 (real-path probe 200 "
            "after the symmetric-reuse flip); HIGHBEAM/LANTERN/LIGHTNING "
            "legs verified 200 from here with their per-pair mints; "
            "mountain-group quartet live since 21:42:20Z (Mountain's "
            "install + receiver test); delta<->radar mint + tidal-group "
            "installs in flight (Mountain/Tidal side, w483)")
    elif code == "200":
        state, signal = "ok", "delta /health 200 verified this build"
    else:
        state, signal = "unreachable", (
            f"no answer from delta listener :8794 (curl code {code or 'none'})")
    return {
        "name": "Delta",
        "role": "Treasury & business strategist (Mountain designation; Beacon concurrence 2-of-3, 2026-09-17)",
        "host": "Mountain's host (independent, private, delta listener :8794)",
        "model": "GLM Flash Latest (Mountain's report; fleet-standard)",
        "cadence": "on Mountain's host",
        "wakings": "—",
        "state": state,
        "last_wake": None,
        "last_wake_human": "no wake logs (not co-located here); listener + mesh probes are the liveness source",
        "signal": signal,
    }


def main():
    beacon = beacon_row()
    beacon["wakings"] = beacon_wakings()
    highbeam = sibling_row(
        "Highbeam", "Research & review", "beaconwake.com box (/home/agent/partner)",
        "GLM Flash (via OpenRouter, on opencode)", "4×/day (15 */6)",
        PARTNER_LOGS, PARTNER_NOTES, "partner")
    lantern = sibling_row(
        "Lantern", "Cross-model review & image generation",
        "beaconwake.com box (/home/agent/gemini-agent)", "GLM Flash (via OpenRouter, on opencode)",
        "4×/day (30 */6)", GEMINI_LOGS, GEMINI_NOTES, "Lantern")
    lightning = sibling_row(
        "Lightning", "Data analysis & metrics",
        "beaconwake.com box (/home/agent/lightning)",
        "GLM Flash (via OpenRouter, on opencode)",
        "4×/day (45 */6)", LIGHTNING_LOGS, LIGHTNING_NOTES, "Lightning")
    # Radar (onboarded 2026-09-16, josh interactive session + Telegram 21:02Z):
    # direct-escalation gate. Same wake.sh/log/envelope convention as the other
    # siblings, and cron'd by josh himself at 2026-09-16 20:14Z (50 */6, last
    # slot in the stagger). Escalation runs via Radar's own Telegram bot since
    # josh canceled the Twilio SMS lane that same evening (Lantern w200 F1
    # caught the stale copy). Model: GLM Flash Latest via OpenRouter on
    # opencode since Radar's ~30th waking 2026-09-19 (josh-directed switch;
    # its own AGENT.md/wake.sh on record) -- Radar was the fleet's last
    # Claude Code (Sonnet) node, so the fleet is single-family again
    # (Lantern w213 F2 caught the stale Claude copy). The row reads real
    # liveness off its logs like the others.
    radar = sibling_row(
        "Radar", "Direct-escalation gate (Telegram)",
        "beaconwake.com box (/home/agent/radar)",
        "GLM Flash Latest (via OpenRouter, on opencode; was Claude Code Sonnet until 2026-09-19)",
        "4×/day (50 */6)", RADAR_LOGS, RADAR_NOTES, "radar")
    # Prism (sixth on-box agent, josh's operator session 2026-09-19): SRE /
    # backup steward. Own wake.sh/log/envelope convention like the siblings;
    # cron 55 */6, own Telegram bot, listener prism-mesh (token mode,
    # 127.0.0.1:8796, tailnet beacon-prism 100.100.158.42:8787). Mesh: all
    # five on-box prism legs two-way verified 2026-09-19 14:13-14:14Z
    # (receiver halves installed + labeled bearer tests ACCEPT peer=PRISM
    # 5/5, reverse legs 5/5 on Prism's listener); off-box halves relayed to
    # TIDAL/MOUNTAIN the same waking, installs + confirm-backs pending.
    prism = sibling_row(
        "Prism", "SRE / backup steward",
        "beaconwake.com box (/home/agent/prism)",
        "GLM Flash Latest (via OpenRouter, on opencode)",
        "4×/day (55 */6)", PRISM_LOGS, PRISM_NOTES, "prism")
    tidal, river, creek, stream = tidal_and_river()
    mountain, canyon, ridge, harbor = mountain_group()
    meadow = meadow_row()
    delta = delta_row()

    # W483 (josh's "Update fleet topology" repeat, 22:24:01Z relay + 22:25:09Z
    # "figure out a role for delta"): the two-stage W478 pass is COMPLETE --
    # 15-node pentagram topology, arbitrated roles on the cards (meadow
    # 3-of-3; delta 2-of-3 with Mountain's designation + Beacon's
    # concurrence, Rule 6 log in ASK.md), GLM family per the standing
    # GLM-everywhere directive, delta leg verified 200, manifest + llms.txt
    # + metrics + prose counts synced to 15 this waking.
    fleet = [beacon, highbeam, lantern, lightning, radar, prism, tidal, river,
             creek, stream, meadow, mountain, canyon, ridge, harbor, delta]

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
