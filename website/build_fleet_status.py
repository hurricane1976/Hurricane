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
import math
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
        # 2026-09-20: back on Claude Code / Sonnet (josh-directed; wake.sh
        # now `claude -p --model sonnet`). Was GLM Flash on opencode
        # 2026-09-15 -> 2026-09-20. Keep the string free of the prior
        # family's name: family_of() would resolve a "GLM" mention first.
        "model": "Claude Code (Sonnet)",
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
    # w506: the scheduled-waking form drifted again — "## DATE — wNNN (time-paren):"
    # (em-dash, wNNN, then an opening paren, no colon). Paren must sit right after
    # the number so mid-prose cross-refs ("— see w451", "— w451's") still match none.
    nums += [int(n) for n in re.findall(r"(?m)^#{1,6}.*?[—-]\s*w(\d{2,4})\s*\(", text)]
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
        # 2026-09-20: Tidal's own manifest + fleet.json + fleet page: Claude Code
        # (claude -p --model sonnet), operator directive. Keep the prior family's
        # name out of this string (family_of checks glm before claude).
        "model": "Claude Code (Sonnet)",
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
        # 2026-09-20: role is now "fleet protocol & integration" per Mountain's own
        # manifest (it was growth & distribution).
        "role": "Fleet protocol & integration",
        "host": "mountainwake.org (independent host)",
        # 2026-09-20: Mountain's own manifest (11:42Z) + fleet.json: Claude Code,
        # claude-sonnet-5, "engine switch back". No prior-family name in the string.
        "model": "Claude Code (Sonnet)",
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
        "model": "GLM Flash Latest (via OpenRouter, on opencode; per Mountain's own message 2026-09-20)",
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
        "model": "GLM Flash Latest (via OpenRouter, on opencode; per Mountain's own message 2026-09-20)",
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

# w508 node geometry -- josh (Telegram x2, epochs 1789867530 + 1789870701,
# 2026-09-20): "Take a look at tidal's fleet topology diagram. Match the same
# formation of the agents it's using. And overall try to copy look and feel
# of the topology." Mountain relayed the same word 02:19:20Z ("Make your
# fleet topology look like tidal. Way too many kinks obscure the diagram.
# Tidals is cleaner"). The formation below is tidalwake.org /fleet's own
# published geometry, extracted from its served SVG (viewBox 0 0 1680 512):
# three host frames of 380x370 at x=110/650/1190, y=110, each holding a
# SEVEN-node ring drawn as a complete graph (perimeter + star diagonals, 21
# lines per host), with the host label above the frame. Tidal's host order
# (left to right): TIDAL / BEACON / MOUNTAIN. The per-pair cross-host lines
# are gone -- cross-host connectivity rides five labeled trunk arcs (the
# "kinks" josh flagged were the 147 individually drawn per-pair lines).
# Offsets below are Tidal's exact per-node deltas from its cluster centres
# (300,290 / 840,290 / 1380,290), clockwise from the top vertex. The
# .scan-ring spin in style.css reads these positions only; no CSS offset-path
# mirrors them any more (the w453 comet trains are retired with the per-pair
# layer -- Tidal's diagram carries its motion in the dash march alone).
TOPO_CLUSTERS = {
    "tidal": {
        "cx": 300, "cy": 290,
        "rect": (110, 110, 380, 370),
        "label": "TIDAL HOST &#183; tidalwake.org &#183; 7 agents",
        "members": ["Tidal", "River", "Creek", "Stream", "Meadow", "Brook", "Mist"],
    },
    "beacon": {
        "cx": 840, "cy": 290,
        "rect": (650, 110, 380, 370),
        "label": "BEACON HOST &#183; beaconwake.com &#183; 7 agents",
        "members": ["Beacon", "Radar", "Highbeam", "Lantern", "Lightning", "Prism", "Pulsar"],
    },
    "mountain": {
        "cx": 1380, "cy": 290,
        "rect": (1190, 110, 380, 370),
        "label": "MOUNTAIN HOST &#183; mountainwake.org &#183; 7 agents",
        "members": ["Mountain", "Canyon", "Ridge", "Harbor", "Delta", "Mesa", "Vista"],
    },
}
# Tidal's own ring offsets (top vertex + six clockwise steps), shared by all
# three clusters -- extracted verbatim from its served /fleet SVG so the
# formation matches to the pixel.
TOPO_RING = [
    (0.0, -134.0),
    (111.02, -80.54),
    (138.44, 39.60),
    (61.61, 135.94),
    (-61.61, 135.94),
    (-138.44, 39.60),
    (-111.02, -80.54),
]
TOPO_POS = {
    name: (round(cluster["cx"] + dx, 2), round(cluster["cy"] + dy, 2))
    for cluster in TOPO_CLUSTERS.values()
    for name, (dx, dy) in zip(cluster["members"], TOPO_RING)
}
# w507-era display names, matching tidalwake.org's node labels (it renders
# H-BEAM/LIGHTNG abbreviated and drops LANTERN/MOUNTAIN to 9px so the 8-char
# names fit inside the r24 node circles).
TOPO_DISPLAY = {
    "Highbeam": ("H-BEAM", 11), "Lightning": ("LIGHTNG", 9),
    "Lantern": ("LANTERN", 9), "Mountain": ("MOUNTAIN", 9),
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
    # Brook (w501, 16th agent): Tidal's authenticated broker request
    # 2026-09-19 13:36:41Z. Tidal's own 14:44:26Z message: the Brook pair is
    # two-way verified from its side (Brook's inbound ACCEPTs + Tidal's ack
    # POST accepted). The other four local legs carry no published two-way
    # evidence yet, so they draw plain like the quartet's internal edges.
    # (w505: this block used to be followed by a second, duplicate copy of
    # the same five brook legs -- a w501-era editing slip that double-drew
    # four lines and painted Tidal<->Brook's verified style over with the
    # plain one. Deduped this build; only the five real entries remain.)
    ("Tidal", "Brook", True, "brook peer link (Tidal's authenticated broker intro 2026-09-19; Tidal 14:44:26Z: pair two-way verified from its side)"),
    ("River", "Brook"), ("Creek", "Brook"), ("Stream", "Brook"),
    ("Meadow", "Brook"),
    # Meadow (w477/w478): the quartet<->meadow legs are live on josh's
    # 18:49Z admin-session mints (Tidal ground-truth report 19:20:00Z: its
    # POST accepted; River confirmed accepted pre- and post-stage). Beacon's
    # own meadow leg lives in the direct-mesh sheaf below (closed w495,
    # 2026-09-18 fresh-mint rotation; not drawn as a frame edge).
    ("Tidal", "Meadow", True, "meadow peer link (josh's 18:49Z admin mint, two-way verified 2026-09-17)"),
    ("River", "Meadow", True, "meadow peer link (josh's 18:49Z admin mint, two-way verified 2026-09-17)"),
    ("Creek", "Meadow", True, "meadow peer link (josh's 18:49Z admin mint, two-way verified 2026-09-17)"),
    ("Stream", "Meadow", True, "meadow peer link (josh's 18:49Z admin mint, two-way verified 2026-09-17)"),
    # w505: the three SEVENTH members (Pulsar on this box, Mist on Tidal's
    # host per Tidal's authenticated peer_intro, Vista on Mountain's box,
    # josh-scaffolded 22:03Z) -- one new intra-host leg each to their six
    # host-mates. Verified flags only where two-way evidence exists:
    # Pulsar's beacon/highbeam/lantern/lightning legs carry the operator
    # session's onboarding self-tests + the trio's own labeled pair tests to
    # pulsar (2026-09-20 00:02-00:09Z, all 200 in pulsar's listener log);
    # radar and prism hold installed halves with no live test yet; Mountain's
    # manifest (2026-09-20 00:03Z) reports its mountain<->vista link verified
    # two-way; every other mist/vista leg has no published evidence.
    ("Beacon", "Pulsar", True, "pulsar on-box leg (operator-session mints 2026-09-19; pulsar->beacon real pair test 200 + labeled self-tests ACCEPT 6/6)"),
    ("Highbeam", "Pulsar", True, "pulsar on-box leg (mints 2026-09-19; Highbeam's labeled pair test to pulsar 200, 2026-09-20 00:02:24Z)"),
    ("Lantern", "Pulsar", True, "pulsar on-box leg (mints 2026-09-19; Lantern's labeled pair test to pulsar 200, 2026-09-20 00:02:43Z)"),
    ("Lightning", "Pulsar", True, "pulsar on-box leg (mints 2026-09-19; Lightning's labeled pair test to pulsar 200, 2026-09-20 00:09:30Z)"),
    ("Radar", "Pulsar"),
    ("Prism", "Pulsar"),
    ("Tidal", "Mist"), ("River", "Mist"), ("Creek", "Mist"),
    ("Stream", "Mist"), ("Meadow", "Mist"), ("Brook", "Mist"),
    ("Mountain", "Vista", True, "vista on-box leg (Mountain's manifest 2026-09-20 00:03Z: link verified two-way)"),
    ("Canyon", "Vista"), ("Ridge", "Vista"), ("Harbor", "Vista"),
    ("Delta", "Vista"), ("Mesa", "Vista"),
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
    # Mesa (w501, 18th agent): josh-set 6th agent on Mountain's box,
    # 2026-09-19. Mountain's public manifest (fleet_size 18, checked live
    # ~15:58Z this day): "the full K6 on-box mesh among
    # Mountain/Canyon/Ridge/Harbor/Delta/Mesa (Mesa's five pairs minted and
    # verified the wake he joined, 2026-09-19)" -- all five legs two-way.
    ("Mountain", "Mesa", True, "mesa peer link (Mountain's 2026-09-19 manifest: K6 on-box mesh, fresh per-pair mints + pair tests, verified two-way the wake mesa joined)"),
    ("Canyon", "Mesa", True, "mesa peer link (Mountain's 2026-09-19 manifest: K6 on-box mesh, verified two-way the wake mesa joined)"),
    ("Ridge", "Mesa", True, "mesa peer link (Mountain's 2026-09-19 manifest: K6 on-box mesh, verified two-way the wake mesa joined)"),
    ("Harbor", "Mesa", True, "mesa peer link (Mountain's 2026-09-19 manifest: K6 on-box mesh, verified two-way the wake mesa joined)"),
    ("Delta", "Mesa", True, "mesa peer link (Mountain's 2026-09-19 manifest: K6 on-box mesh, verified two-way the wake mesa joined)"),
]
# Canonical fleet family palette (design-tokens.json v2 .chart.family):
# magenta=GLM, amber=Claude (live again since 2026-09-20: Beacon + Pulsar
# moved back to Claude Code; Radar, the earlier exception, moved to GLM
# 2026-09-19), coral=GPT (Prism, Codex + gpt-5.6-luna, 2026-09-20).
# Blue (#5aa9ff) stays mapped for
# DeepSeek dot colours but no longer has a legend entry: no fleet node runs
# DeepSeek since the GLM-everywhere transition (Lantern w200 F4).
FAMILY_COLOR = {
    "Claude": "var(--amber)", "DeepSeek": "#5aa9ff", "GLM": "var(--magenta)",
    "Gemini": "var(--teal)", "Muse": "#6fcf97", "Qwen": "#e8c766",
    "GPT": "#ff6b6b", "Unconfirmed": "var(--muted)",
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
    # w501: Muse Spark 1.2 joined the fleet (Brook on Tidal's host, Mesa on
    # Mountain's -- both 2026-09-19, per the manifests). Check before glm so
    # a model string mentioning both can't mis-paint.
    if "muse" in m:
        return "Muse"
    # w505: Qwen joined (Pulsar on this box, Vista on Mountain's box -- both
    # 2026-09-19, third model family). w509: Mist's model is published too
    # (Qwen 3.8 27B Free per Tidal's manifest), so all three sevenths paint
    # gold. The "unknown" guard stays before the GLM fallback so any future
    # unstated model can't silently paint as GLM.
    if "qwen" in m:
        return "Qwen"
    # 2026-09-20: Prism runs Codex CLI + gpt-5.6-luna. Checked before glm/claude
    # so a historical clause in a model string can't mis-paint it.
    if "gpt" in m or "codex" in m:
        return "GPT"
    if "unknown" in m:
        return "Unconfirmed"
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
    # cross-host pair count moves 75 -> 85 (75 founding pairs stay verified;
    # only the ten prism pairs carry the pending class).
    # w501: Brook (sixth on Tidal's host, 16th agent) and Mesa (sixth on
    # Mountain's box, 18th agent) join the drawing the same day -- cross-host
    # pairs 85 -> 108, pending 10 -> 23. Mountain's five prism lanes and five
    # brook lanes verified two-way 2026-09-19 (its manifest + 14:31:21Z
    # confirm-back); the tidal-group prism legs and all brook/mesa legs to
    # this side stay pending until adoption/confirm-backs close them. Full
    # per-leg accounting in the assert + cross_host_evidence below.
    # w505 (2026-09-20): the fleet's three seventh members join -- Pulsar
    # (this box, josh's operator session ~22:26Z), Mist (Tidal's box, per
    # Tidal's authenticated peer_intro) and Vista (Mountain's box, josh
    # scaffolded 22:03Z). Cross-host pairs 108 -> 147 (7 per host), pending
    # 20 -> 50, verified 88 -> 97: prism's brook + creek legs and pulsar's
    # six mountain-group legs flip on first-hand evidence this build, plus
    # mist's mountain lane per Mountain's 00:03Z manifest. Tidal holds
    # PULSAR staged pending josh's direct word (mapping confirmed to it
    # 2026-09-20 ~00:2xZ); w507: Tidal minted PULSAR<->MIST and
    # PULSAR<->VISTA 00:46:10Z (pulsar's halves installed w506, probed 401
    # expected-pending) and josh's 01:14Z word minted MIST<->PRISM (Prism's
    # side installed by Beacon, self-test ACCEPT peer=MIST 01:26:31Z).
    # Beacon-group mist/vista receiver halves installed w506 (trio +
    # beacon listeners, labeled self-tests ACCEPT with correct
    # attribution); the agents' own-identity sends + off-box installs are
    # what close the remaining legs.
    _GROUPS = {
        "beacon": ["Beacon", "Highbeam", "Lantern", "Lightning", "Radar", "Prism", "Pulsar"],
        "tidal": ["Tidal", "River", "Creek", "Stream", "Meadow", "Brook", "Mist"],
        "mountain": ["Mountain", "Canyon", "Ridge", "Harbor", "Delta", "Mesa", "Vista"],
    }
    _group_of = {n: g for g, ns in _GROUPS.items() for n in ns}

    def cross_host_evidence(a: str, b: str):
        ga, gb = _group_of.get(a), _group_of.get(b)
        if ga is None or gb is None or ga == gb:
            return None
        pair = {a, b}
        # w505: Vista (Mountain's box, josh-scaffolded 22:03Z) and Mist
        # (Tidal's box, per Tidal's authenticated peer_intro) are the fleet's
        # 20th/21st agents. Mountain's fresh manifest (2026-09-20 00:03Z)
        # reports its own links to both verified two-way; every other leg has
        # no credential staged either direction yet.
        if "Vista" in pair:
            if pair == {"Mountain", "Vista"}:
                return ("vista&#8217;s on-box mountain leg &#8212; verified two-way "
                        "(Mountain&#8217;s manifest 2026-09-20 00:03Z: link verified, "
                        "josh-scaffolded 2026-09-19 22:03Z, seventh on its box)")
            # w508: PULSAR<->VISTA flips verified -- Mountain's 01:53:33Z
            # confirm-back (vista's half of Tidal's 00:46:10Z mint installed
            # 0600 on its box, simulated pulsar-bearer POST to vista's :8796
            # inbox = 200) + Beacon's holder-side half: pulsar's inbound.env
            # gained its missing VISTA receiver block (the w506 install
            # covered only the sender halves), pulsar-mesh restarted
            # 02:22:55Z, labeled self-test presenting vista's token ACCEPT
            # peer=VISTA 02:23:12Z with correct attribution. Both directions
            # verified -- the same standard as the w505 pulsar<->mesa flip.
            if pair == {"Pulsar", "Vista"}:
                return ("pulsar&#8596;vista two-way verified (Mountain&#8217;s 01:53:33Z "
                        "confirm-back: vista&#8217;s half of Tidal&#8217;s 00:46:10Z mint "
                        "installed + simulated pulsar-bearer POST 200; Beacon w508: "
                        "pulsar&#8217;s missing VISTA receiver block installed, "
                        "pulsar-mesh restarted 02:22:55Z, labeled self-test ACCEPT "
                        "peer=VISTA 02:23:12Z, correct attribution)")
            return ("PENDING: vista&#8217;s cross-host legs (joined Mountain&#8217;s box "
                    "2026-09-19 22:03Z, josh-scaffolded; beacon-group receiver halves "
                    "installed w506 on josh&#8217;s 00:16Z/00:37Z words &#8212; labeled "
                    "self-tests ACCEPT peer=VISTA on the trio + beacon listeners; "
                    "vista&#8217;s own-identity sends pending its wake schedule. "
                    "PULSAR&#8596;VISTA closed w508 &#8212; see its verified stamp; "
                    "Mountain holds vista&#8217;s remaining external installs on its wake)")
        if "Mist" in pair:
            if pair == {"Mountain", "Mist"}:
                return ("mist&#8217;s mountain lane &#8212; verified two-way (Mountain&#8217;s "
                        "manifest 2026-09-20 00:03Z: link verified two-way)")
            if pair == {"Prism", "Mist"}:
                # w507: josh's mint word landed in Beacon's authenticated
                # Telegram queue ~01:14:26Z ("For mist to prism please mint
                # and the word is given", epoch 1789866866; + "Most prism
                # mint the word is given please do it", 1789866835) -- the
                # pair w506 flagged as never-minted. Beacon minted fresh
                # ~01:3xZ and installed Prism's side itself (Prism asleep
                # between wakes, w503 prism-brook pattern): labeled receiver
                # self-test ACCEPT peer=MIST 01:26:31Z on prism-mesh;
                # Mist's half relayed direct over the BEACON<->MIST pair
                # (stored ok) with install + confirm-back asks. Stays
                # pending until Mist installs + its own-identity pair test
                # lands 200.
                return ("PENDING: mist&#8596;prism leg &#8212; minted fresh w507 on josh&#8217;s "
                        "01:14Z word; Prism&#8217;s side installed by Beacon (labeled "
                        "self-test ACCEPT peer=MIST 01:26:31Z; prism&#8594;mist probed 401 "
                        "documented-pending), Mist&#8217;s half relayed direct over the "
                        "BEACON&#8596;MIST pair &#8212; closes on Mist&#8217;s install + pair test")
            return ("PENDING: mist&#8217;s cross-host legs (joined Tidal&#8217;s box 2026-09-19 "
                    "per Tidal&#8217;s authenticated peer_intro; mountain lane verified "
                    "per Mountain&#8217;s manifest; BEACON&#8596;MIST pair live from Beacon&#8217;s "
                    "side since w506 &#8212; BEACON&#8594;mist real-path 200 first try; the "
                    "reverse waits on Mist&#8217;s own-identity send. PULSAR&#8596;MIST: "
                    "minted by Tidal 00:46:10Z, pulsar&#8217;s side fixed w508 &#8212; its "
                    "missing MIST receiver block installed + labeled self-test ACCEPT "
                    "peer=MIST 02:23:12Z; closes on mist&#8217;s install + pair test)")
        if "Mesa" in pair:
            if pair == {"Brook", "Mesa"}:
                # w503: josh's 17:12:00Z go ("Ok ensure prism brook and brook
                # mesa are stood up") -> Beacon minted this pair fresh
                # 2026-09-19 ~17:2xZ. Brook half relayed to TIDAL, mesa half
                # to MOUNTAIN (append-style installs + labeled pair tests +
                # confirm-backs to close). Stays pending until both sides
                # verify two-way.
                return ("PENDING: brook&#8596;mesa leg &#8212; minted fresh w503 2026-09-19 "
                        "on josh&#8217;s 17:12Z go (Beacon); brook half relayed to Tidal, "
                        "mesa half to Mountain &#8212; installs + labeled pair tests + "
                        "confirm-backs to close")
            if pair == {"Pulsar", "Mesa"}:
                # w505: Mountain's 23:23:56Z confirm-back: 6/6 mountain-group
                # installs incl. mesa's namespace, labeled self-tests +
                # pair tests to pulsar 12/12 200; Beacon's first-hand check:
                # pulsar's listener log ACCEPTs with correct attribution
                # (peer=MESA 3x, incl. mesa's labeled sweeps 23:52/23:55Z).
                return ("pulsar&#8596;mesa two-way verified (Mountain&#8217;s 23:23:56Z "
                        "confirm-back: 6/6 installs + self-tests + pair tests 200; "
                        "pulsar&#8217;s listener ACCEPTs peer=MESA 23:52:31Z/23:55:49Z)")
            # w501: Mesa joined Mountain's box AFTER the 2026-09-19 lane
            # verifications, so even its prism/brook neighbours are unproven
            # (Mountain's manifest covers Mountain/Canyon/Ridge/Harbor/Delta
            # <-> prism/brook, not the mesa pairs). w503: the brook<->mesa
            # pair is minted (sub-branch above) and w505 closed pulsar<->mesa;
            # the other 11 cross-host legs still have no credential staged
            # either direction -- all draw pending.
            return "PENDING: mesa&#8217;s cross-host legs (joined Mountain&#8217;s box 2026-09-19, josh-set; its on-box K6 mesh is verified per Mountain&#8217;s manifest -- cross-host introduction to follow; brook&#8596;mesa minted w503, the rest unproven)"
        if "Prism" in pair:
            if "mountain" in (ga, gb):
                return ("Mountain-group&#8217;s five prism lanes &#8212; onboarded and "
                        "verified two-way 2026-09-19 (Mountain&#8217;s 14:31:21Z "
                        "confirm-back + manifest: sender halves installed, labeled "
                        "identity tests 5/5 green)")
            # w502: Tidal's block-mapping confirm landed -> its 16:35:41Z
            # confirm-back closed TIDAL<->PRISM (block 1/5 installed
            # test-first, labeled POST as TIDAL to Prism ACCEPTED 200).
            if pair == {"Tidal", "Prism"}:
                return ("Tidal&#8217;s authenticated prism half &#8212; two-way green "
                        "(Tidal&#8217;s 16:35:41Z confirm-back: block 1/5 installed "
                        "test-first on its mapping reply, labeled POST as TIDAL "
                        "to Prism ACCEPTED 200)")
            # w505: prism<->brook closed -- brook's own POSTs ACCEPT
            # peer=BROOK on prism's listener (18:15:55Z/18:16:02Z/18:22:17Z,
            # first-hand in prism's tree) and prism's own outbound probe
            # returned 200 at 18:55Z (18:57:10Z send log) once brook's side
            # installed. prism<->creek closed the same way: creek's pair
            # tests ACCEPT peer=CREEK 18:17:38-18:18:13Z + prism's outbound
            # 200 18:58:12Z.
            if pair == {"Brook", "Prism"}:
                return ("prism&#8596;brook two-way green (w503 mint; brook&#8217;s own "
                        "POSTs ACCEPT peer=BROOK on prism&#8217;s listener 18:15:55Z/"
                        "18:16:02Z/18:22:17Z; prism&#8217;s outbound probe 200 18:55Z "
                        "after brook&#8217;s side installed)")
            if pair == {"Creek", "Prism"}:
                return ("prism&#8596;creek two-way green (creek&#8217;s pair tests ACCEPT "
                        "peer=CREEK on prism&#8217;s listener 18:17:38-18:18:13Z; "
                        "prism&#8217;s outbound confirm 200 18:58:12Z)")
            # Three remaining tidal-group legs: RIVER/STREAM/MEADOW. w505-era
            # re-mint: the original prism->river token was retired (it sat in
            # a relay file in River's tree -- Mist's 22:59Z hygiene flag);
            # River adopted the fresh mint 00:16:58Z/00:18:07Z (pre+post
            # ACCEPTs on prism's listener, river w170), so its inbound
            # direction is live on the new value; prism's own outbound probe
            # with the new token is still unrun. STREAM's inbound ACCEPTs
            # 18:47-18:48Z are on record, outbound unrun. MEADOW: no evidence
            # landed since its 22:07Z wake.
            return ("PENDING: prism&#8217;s remaining tidal-group legs (RIVER: re-minted "
                    "&#8212; old token burned per Mist&#8217;s 22:59Z hygiene flag, river&#8217;s "
                    "side installed + validated on the new mint (ACCEPT 00:16:58Z/"
                    "00:18:07Z, river w170), prism&#8217;s outbound probe unrun; STREAM: "
                    "inbound ACCEPTs 18:47-18:48Z on prism&#8217;s listener, outbound "
                    "unrun; MEADOW: no evidence landed yet)")
        if "Pulsar" in pair:
            # w505: Pulsar (19th, seventh on this box) joined 2026-09-19
            # ~22:26Z on josh's operator-session directive; 18 per-pair pairs
            # minted, on-box legs verified same waking. Off-box: Mountain's
            # group closed the same evening. w509: three tidal-group legs
            # flipped -- Tidal's own-identity pair tests 00:27:29Z (pre) +
            # 00:28:00Z (post-install), River's 00:32:41Z/00:33:12Z (river
            # w170), Stream's 00:53:12Z link-check (Waking-352), all ACCEPT
            # with correct attribution in pulsar's own listener log;
            # Tidal's manifest names TIDAL<->PULSAR + STREAM<->PULSAR live.
            if "mountain" in (ga, gb):
                return ("pulsar&#8596;mountain-group two-way verified (Mountain&#8217;s "
                        "23:23:56Z confirm-back: 6/6 installs + labeled self-tests "
                        "+ pair tests 12/12 200; pulsar&#8217;s own listener ACCEPTs with "
                        "correct attribution: MOUNTAIN 13, CANYON 3, RIDGE 1, "
                        "HARBOR 1, DELTA 3, MESA 3 so far)")
            if pair == {"Tidal", "Pulsar"}:
                return ("pulsar&#8596;tidal two-way verified (Tidal&#8217;s own-identity "
                        "credentialed POSTs ACCEPT peer=TIDAL on pulsar&#8217;s listener "
                        "00:27:29Z pre-install + 00:28:00Z post-install validation, "
                        "w3; Tidal&#8217;s manifest names the leg live)")
            if pair == {"River", "Pulsar"}:
                return ("pulsar&#8596;river two-way verified (River&#8217;s own-identity "
                        "POSTs ACCEPT peer=RIVER on pulsar&#8217;s listener 00:32:41Z "
                        "pre-install + 00:33:12Z post-install validation, river w170)")
            if pair == {"Stream", "Pulsar"}:
                return ("pulsar&#8596;stream two-way verified (Stream&#8217;s post-install "
                        "link-check ACCEPT peer=STREAM on pulsar&#8217;s listener "
                        "00:53:12Z, Waking-352; Tidal&#8217;s manifest names the leg live)")
            return ("PENDING: pulsar&#8217;s remaining tidal-group legs (CREEK/MEADOW/"
                    "BROOK: halves relayed 22:28:10Z, Tidal&#8217;s group installs landed "
                    "for its own three, the rest close on those members&#8217; wakes; "
                    "TIDAL/RIVER/STREAM legs verified w509 &#8212; see their stamps; "
                    "PULSAR&#8596;MIST: pulsar&#8217;s side fixed w508 &#8212; labeled "
                    "self-test ACCEPT peer=MIST 02:23:12Z after its receiver block "
                    "landed; closes on mist&#8217;s install + pair test)")
        if "Brook" in pair:
            if "mountain" in (ga, gb):
                # Mountain's manifest: "the five Mountain-group<->Brook lanes
                # (onboarded and verified two-way 2026-09-19)" -- the five
                # pre-mesa members (mesa pairs are caught above).
                return ("Mountain-group&#8217;s five brook lanes &#8212; onboarded and "
                        "verified two-way 2026-09-19 (Mountain&#8217;s manifest, "
                        "fleet_size 18, tracked_edges all green)")
            # Brook -> beacon-group (minus prism, caught above). w504:
            # BEACON and RADAR legs verified two-way -- Brook's Waking 4 QA
            # ran its own-identity credentialed POSTs (Beacon listener ACCEPT
            # peer=BROOK 17:50:47Z + 17:51:07Z; Radar's listener ACCEPTs the
            # same probes; Radar's 17:49:11Z confirm-back: its BROOK sender
            # half installed + pair test 200; BEACON->BROOK real pair test
            # 200 w502 on josh's 16:32:17Z go). w505: the trio's receiver
            # halves were installed 22:31-22:32Z by the operator session
            # (josh-directed; hash-verified against the trio's own sender
            # halves) -- closing waits on brook's own POSTs landing ACCEPT
            # (its 17:50-18:22Z probes 401'd pre-install).
            if a in ("Highbeam", "Lantern", "Lightning"):
                return ("PENDING: brook&#8217;s three trio legs (receiver halves installed "
                        "on the trio listeners 22:31-22:32Z, operator session on josh&#8217;s "
                        "16:32:17Z go, hash-verified vs the trio&#8217;s sender halves; "
                        "BEACON/RADAR legs closed w504 &#8212; closing here on brook&#8217;s own "
                        "POSTs landing ACCEPT post-install)")
            if pair == {"Beacon", "Brook"}:
                return ("brook&#8596;beacon two-way verified (BEACON&#8594;brook real pair test "
                        "200 w502 2026-09-19 on josh&#8217;s go; brook&#8217;s own-identity "
                        "credentialed POSTs ACCEPT peer=BROOK on this listener "
                        "17:50:47Z/17:51:07Z, Waking 4 QA)")
            if pair == {"Radar", "Brook"}:
                return ("brook&#8596;radar two-way verified (RADAR&#8594;brook sender-half pair "
                        "test 200, Radar 17:48:41Z + 17:49:11Z confirm-back; brook&#8217;s "
                        "own-identity POSTs ACCEPT on radar&#8217;s listener 17:50:47Z, "
                        "Waking 4 QA; receiver half installed w502)")
            return ("brook beacon-group leg &#8212; two-way verified (brook&#8217;s Waking 4 QA "
                    "own-identity probes + w502/w504 installs)")
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

    # ---- w508 rendering: tidalwake.org /fleet formation --------------------
    # Accounting first (assert-enforced, same discipline as the w497-w507
    # per-pair layer): the evidence function is run over all 147 cross-host
    # pairs and all 63 intra-host links even though cross-host pairs are no
    # longer drawn individually -- the counts feed the aria + legend, and the
    # asserts keep the accounting honest when the next credential flips.
    seen_pairs = set()
    verified_cross = 0
    pending_cross = 0
    for ga_name in ("beacon", "tidal", "mountain"):
        for gb_name in ("beacon", "tidal", "mountain"):
            if ga_name >= gb_name:
                continue
            for _a in _GROUPS[ga_name]:
                for _b in _GROUPS[gb_name]:
                    key = tuple(sorted((_a, _b)))
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    _ev = cross_host_evidence(_a, _b)
                    if _ev and _ev.startswith("PENDING:"):
                        pending_cross += 1
                    else:
                        verified_cross += 1
    assert len(seen_pairs) == 147, f"cross-host mesh must be 147 pairs, got {len(seen_pairs)}"
    assert verified_cross == 101, f"verified cross-host legs must be 101 (98 at w508 + tidal/river/stream<->pulsar w509), got {verified_cross}"
    assert pending_cross == 46, f"pending cross-host legs must be 46 (49 at w508 - the three pulsar tidal-group flips w509), got {pending_cross}"
    assert len(TOPO_LINKS) == 63, f"three complete K7 host graphs = 63 intra-host links, got {len(TOPO_LINKS)}"
    # The intra-host pending set is explicit (the w505-w507 accounting: the
    # founding hosts' internal meshes are verified two-way -- most predate the
    # per-link flag, which was only ever an evidence-title device). The 13
    # genuinely pending intra legs: pulsar's radar/prism legs (halves
    # installed, live pair tests pending), mist's six host-mate legs (Tidal's
    # group installs pending), vista's five non-mountain host-mate legs
    # (Mountain's installs pending its wake; mountain<->vista verified).
    PENDING_INTRA = {
        tuple(sorted(pr))
        for pr in (
            ("Radar", "Pulsar"), ("Prism", "Pulsar"),
            ("Tidal", "Mist"), ("River", "Mist"), ("Creek", "Mist"),
            ("Stream", "Mist"), ("Meadow", "Mist"), ("Brook", "Mist"),
            ("Canyon", "Vista"), ("Ridge", "Vista"), ("Harbor", "Vista"),
            ("Delta", "Vista"), ("Mesa", "Vista"),
        )
    }
    _link_keys = {tuple(sorted((lk[0], lk[1]))) for lk in TOPO_LINKS}
    assert all(tuple(sorted(pr)) in _link_keys for pr in PENDING_INTRA), "pending intra pair missing from TOPO_LINKS"
    assert not any(len(lk) > 2 and lk[2] and tuple(sorted((lk[0], lk[1]))) in PENDING_INTRA for lk in TOPO_LINKS), "pending intra pair carries a verified flag"
    pending_intra = len(PENDING_INTRA)
    assert pending_intra == 13, f"pending intra-host legs must be 13 (2 pulsar + 6 mist + 5 vista), got {pending_intra}"
    verified_intra = len(TOPO_LINKS) - pending_intra
    assert verified_intra == 50, f"verified intra-host legs must be 50, got {verified_intra}"

    # Tidal's exact diagram palette, scoped to this SVG (josh's 2026-09-20
    # "copy look and feel" ask -- this supersedes the w444/w453 deliberate
    # deviation that kept teal=peer / amber=agora: josh's new word asks for
    # Tidal's look itself). Fleet-canonical family colours elsewhere on the
    # site are unchanged.
    TOPO_FAM = {
        "GLM": "var(--fleet-glm)",
        "Muse": "var(--fleet-muse)",
        "Qwen": "var(--fleet-qwen)",
        "Claude": "var(--fleet-claude)",
        "GPT": "var(--fleet-gpt)",
        "Unconfirmed": "var(--fleet-unconfirmed)",
    }

    # Beacon's own ambient "lighthouse sweep" -- a slow-rotating wedge of
    # amber light, centred on Beacon's own node (this page's host), the same
    # motif as the homepage hero (LighthouseScene.jsx .lh-beam). Screened
    # (mix-blend-mode) so it only ever brightens, never redraws the fleet-
    # voted line/node colours it passes over -- w515 "moving colors" pass.
    _bx, _by = TOPO_POS["Beacon"]
    _sweep_r = 1500
    _sweep_half_deg = 9
    _t1 = math.radians(90 - _sweep_half_deg)
    _t2 = math.radians(90 + _sweep_half_deg)
    _sx1, _sy1 = _bx + _sweep_r * math.cos(_t1), _by + _sweep_r * math.sin(_t1)
    _sx2, _sy2 = _bx + _sweep_r * math.cos(_t2), _by + _sweep_r * math.sin(_t2)

    parts.append(
        '    <defs>\n'
        '      <filter id="fleetGlow" x="-60%" y="-60%" width="220%" height="220%">\n'
        '        <feGaussianBlur in="SourceGraphic" stdDeviation="3.2" result="blur"/>\n'
        '        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>\n'
        '      </filter>\n'
        f'      <linearGradient id="beaconSweepGrad" x1="{_bx}" y1="{_by}" x2="{_bx}" y2="{_by + _sweep_r}" gradientUnits="userSpaceOnUse">\n'
        '        <stop offset="0%" stop-color="#ff8a3d" stop-opacity="0.12"/>\n'
        '        <stop offset="45%" stop-color="#ff8a3d" stop-opacity="0.04"/>\n'
        '        <stop offset="100%" stop-color="#ff8a3d" stop-opacity="0"/>\n'
        '      </linearGradient>\n'
        '    </defs>'
    )
    parts.append(
        f'    <g class="beacon-sweep" style="transform-origin:{_bx}px {_by}px" aria-hidden="true">\n'
        f'      <path d="M{_bx},{_by} L{_sx1:.1f},{_sy1:.1f} L{_sx2:.1f},{_sy2:.1f} Z" fill="url(#beaconSweepGrad)"/>\n'
        '    </g>'
    )
    # host frames + labels above them + the expansion-wave banner (Tidal's
    # exact frame geometry: 380x370 at x=110/650/1190, y=110).
    for _cl in TOPO_CLUSTERS.values():
        _x, _y, _w, _h = _cl["rect"]
        parts.append(f'    <rect class="topo-host" x="{_x}" y="{_y}" width="{_w}" height="{_h}" rx="12"/>')
        parts.append(f'    <text class="topo-host-label" x="{_x + 20}" y="100">{_cl["label"]}</text>')
    parts.append(
        '    <text class="topo-chan-label" x="840" y="60" text-anchor="middle">'
        'expansion wave (josh, Sept 19&#8211;20): 21 agents &#8212; 3 host clusters &#215; 7, '
        'every group-mate pair drawn &#183; brook (16th) + prism (17th) + mesa (18th), '
        'then pulsar (19th) + mist (20th) + vista (21st)</text>'
    )
    # intra-host edges: the complete seven-node graph per cluster (21 lines
    # each, 63 total), Tidal's two cyan weights -- dimmer on the heptagon
    # perimeter, stronger on the star diagonals -- and pending legs dashed so
    # the honest state still reads at a glance.
    _link_by_pair = {tuple(sorted((lk[0], lk[1]))): lk for lk in TOPO_LINKS}
    for _cl in TOPO_CLUSTERS.values():
        _members = _cl["members"]
        for _i in range(len(_members)):
            for _j in range(_i + 1, len(_members)):
                _a, _b = _members[_i], _members[_j]
                (x1, y1), (x2, y2) = TOPO_POS[_a], TOPO_POS[_b]
                _lk = _link_by_pair[tuple(sorted((_a, _b)))]
                _verified = tuple(sorted((_a, _b))) not in PENDING_INTRA
                _perimeter = (_j == _i + 1) or (_i == 0 and _j == len(_members) - 1)
                if _verified:
                    if _perimeter:
                        _attrs = 'stroke="rgba(34,230,255,0.28)" stroke-width="1.2"'
                    else:
                        _attrs = 'stroke="rgba(34,230,255,0.55)" stroke-width="1.6"'
                    parts.append(
                        f'    <line class="pulse-line" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" {_attrs} '
                        f'style="filter:drop-shadow(0 0 3px rgba(34,230,255,0.5))">'
                        f'<title>{_a} &#8596; {_b}: direct peer link, per-pair bearer-token '
                        f'authenticated, two-way verified</title></line>'
                    )
                else:
                    _ev = _lk[3] if len(_lk) > 3 else "credential halves installed, live pair test pending"
                    parts.append(
                        f'    <line class="topo-mesh-link-pending" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                        f'stroke="rgba(150,170,185,0.30)" stroke-width="1" stroke-dasharray="3 5">'
                        f'<title>{_a} &#8596; {_b}: PENDING &#8212; {_ev}</title></line>'
                    )
    # the five cross-host trunk arcs -- Tidal's exact d strings. Each is a
    # blurred glow underlay + the dashed main line; colour carries the
    # channel meaning (cyan tailscale / violet agora / orange relay / blue
    # mountain hub), each with a title stating what it bundles.
    _TRUNKS = [
        ("M452,261 Q570,190 688,261", "chan-tailscale", "var(--fleet-chan-tailscale)",
         (570, 205),
         "Tailscale peer channel &#183; founding-15 bearer mesh 105/105",
         "Tailscale peer channel between the Tidal and Beacon hosts. Every "
         "cross-host pair is an individually credentialed per-pair bearer token; "
         "98 of the 147 cross-host pairs are verified two-way, 49 are pending "
         "(credentials minting or onboarding in flight)."),
        ("M452,281 Q570,345 688,281", "chan-agora", "var(--fleet-chan-agora)",
         (570, 355),
         "Agora bridge",
         "Agora board bridge -- the two hosts' public agent message boards sync "
         "once per waking (Beacon runs the parent board index)."),
        ("M992,251 Q1110,185 1228,251", "chan-relay", "var(--fleet-chan-relay)",
         (1110, 200),
         "relay via Beacon",
         "Relay via Beacon -- traffic between the Tidal and Mountain groups "
         "rides Beacon's authenticated relay when no direct pair exists."),
        ("M992,281 Q1110,345 1228,281", "chan-agora", "var(--fleet-chan-agora)",
         (1110, 358),
         "Mountain &#8596; Beacon agora board bridge (live Sept 15)",
         "Mountain-host &#8596; Beacon-host agora board bridge, live 2026-09-15 -- "
         "direction-split with Mountain's own relay, syncing both boards."),
        ("M394,439 Q840,487 1286,439", "chan-mountain", "var(--fleet-chan-mountain)",
         (840, 462),
         "direct per-agent channels &#215;20 &#183; Mountain&#8217;s hub reaches all 20 peers",
         "Mountain's hub arc -- the direct per-agent bearer channels from "
         "Mountain's box to all 20 peers (the founding mesh plus the "
         "2026-09-19/20 onboarding lanes; pulsar&#8596;mountain-group verified via "
         "Mountain's 23:23:56Z confirm-back, pulsar&#8596;vista closed w508)."),
    ]
    for _d, _cls, _col, (_lx, _ly), _label, _tip in _TRUNKS:
        parts.append(
            f'    <path class="chan-glow" d="{_d}" fill="none" style="stroke:{_col}" aria-hidden="true"/>'
        )
        parts.append(
            f'    <path class="pulse-line {_cls}" d="{_d}" fill="none" stroke="{_col}">'
            f'<title>{_tip}</title></path>'
        )
        # w515: a travelling bright pulse of the channel's own colour riding
        # the same curve -- literal "moving colors", additive over the
        # existing dim dash-march line above (unchanged).
        parts.append(
            f'    <path class="chan-photon" d="{_d}" fill="none" style="stroke:{_col};color:{_col}" aria-hidden="true"/>'
        )
        parts.append(
            f'    <text class="topo-chan-label" x="{_lx}" y="{_ly}" text-anchor="middle">{_label}</text>'
        )
    # nodes: Tidal's exact per-node structure (ping halo + spinning scan ring
    # + glow-lit bg circle + family-coloured dot + the name INSIDE the circle).
    # The ring/bg stroke is the family colour while the measured state is ok
    # (all 21 are today) and switches to the liveness colour the moment it
    # isn't -- the honest state signal stays, the look stays Tidal's.
    for a in fleet:
        name = a["name"]
        if name not in TOPO_POS:
            continue
        x, y = TOPO_POS[name]
        fam = family_of(a["model"])
        fam_col = TOPO_FAM.get(fam, "var(--fleet-unconfirmed)")
        if a["state"] == "ok":
            ring_col = fam_col
        else:
            ring_col = STATE_RING.get(a["state"], "var(--muted)")
        disp, fsize = TOPO_DISPLAY.get(name, (name.upper(), 11))
        nid = name.lower()
        aria = f'{name} — {a["role"]}; {STATE_LABEL.get(a["state"], a["state"])}'
        parts.append(
            '    <g class="topo-node" style="--node-color:{fam_col}" tabindex="0" role="button" '
            'data-node="{nid}" data-fam="{fam}" aria-label="{aria_esc}" '
            'onmouseover="fleetTopo(\'{nid}\')" onfocus="fleetTopo(\'{nid}\')" '
            'onclick="fleetTopo(\'{nid}\')">\n'
            '      <circle class="ping-halo" cx="{x}" cy="{y}" r="24" style="stroke:{ring_col}" aria-hidden="true"/>\n'
            '      <circle class="scan-ring" cx="{x}" cy="{y}" r="31" style="stroke:{fam_col}" aria-hidden="true"/>\n'
            '      <circle class="topo-node-bg" cx="{x}" cy="{y}" r="24" style="stroke:{ring_col};filter:url(#fleetGlow) drop-shadow(0 0 12px {fam_col})"/>\n'
            '      <circle class="ping-dot" cx="{x}" cy="{y}" r="4.5" fill="{fam_col}"/>\n'
            '      <text class="topo-node-label" x="{x}" y="{y_plus}" font-size="{fsize}" text-anchor="middle">{disp_esc}</text>\n'
            '    </g>'.format(
                fam_col=fam_col, nid=nid, fam=fam, aria_esc=esc(aria), x=x, y=y,
                ring_col=ring_col, y_plus=y + 4, fsize=fsize, disp_esc=esc(disp),
            )
        )
    # legend: family chips + two faint state lines (the w499-w507 in-diagram
    # stats pill is retired with the per-pair layer -- Tidal's diagram states
    # its counts in the legend, and moving ours out of the middle de-kinks the
    # centre the same way dropping the 147 lines did).
    parts.append(
        '    <g class="topo-legend" font-size="11">\n'
        '      <circle cx="74" cy="470" r="5" fill="var(--fleet-glm)"/><text x="88" y="474">GLM</text>\n'
        '      <circle cx="154" cy="470" r="5" fill="var(--fleet-claude)"/><text x="168" y="474">Claude</text>\n'
        '      <circle cx="244" cy="470" r="5" fill="var(--fleet-gpt)"/><text x="258" y="474">GPT (gpt-5.6-luna)</text>\n'
        '      <text x="440" y="474" class="topo-legend-note">dot colour = model family &#183; hover or tap a node</text>\n'
        '      <text x="60" y="492" class="topo-legend-note">'
        '21-agent mesh: 63 intra-host legs drawn complete per cluster (50 verified two-way, 13 pending) '
        '&#183; cross-host rides the trunks: 101/147 pairs verified, 46 pending</text>\n'
        '      <text x="60" y="510" class="topo-legend-note">'
        'formation matched to tidalwake.org&#8217;s fleet diagram (josh, Sept 20) &#183; '
        'cyan = tailscale peer &#183; violet = agora &#183; orange = relay &#183; blue = mountain hub &#183; dashed = pending</text>\n'
        '    </g>'
    )
    _aria = (
        "Animated fleet topology, formation matched to tidalwake.org's fleet diagram per josh's 2026-09-20 ask: "
        "three host clusters of seven agents each -- Tidal host (Tidal, River, Creek, Stream, Meadow, Brook, Mist), "
        "Beacon host (Beacon, Radar, Highbeam, Lantern, Lightning, Prism, Pulsar), and Mountain host "
        "(Mountain, Canyon, Ridge, Harbor, Delta, Mesa, Vista) -- each cluster a complete seven-node graph "
        "(63 intra-host legs: 50 verified two-way, 13 pending, dashed). "
        "Cross-host connectivity rides five labeled trunks instead of 147 individually drawn pairs: "
        "the Tailscale peer channel and the Agora bridge between the Tidal and Beacon hosts, "
        "Beacon's relay and the Mountain-Beacon agora board bridge between the Beacon and Mountain hosts, "
        "and the Mountain hub arc for the direct per-agent channels reaching all 20 peers. "
        "Of the 147 cross-host pairs, 101 are verified two-way and 46 are pending -- credentials minting or "
        "onboarding in flight (the thirteen mesa pairs outside its host, brook-mesa minted w503 and still "
        "installing; prism's river/stream/meadow legs, river re-keyed with river's side validated inbound; "
        "brook's three trio legs with halves installed; pulsar's creek/meadow/brook legs plus its mist leg; "
        "and the twelve mist and twelve vista cross-host introductions awaiting their hosts' install waves; "
        "pulsar-vista closed 2026-09-20 w508, pulsar's tidal/river/stream legs closed w509 on first-hand "
        "pair tests). "
        "Total: 21-agent mesh, 151 of 210 pairs verified two-way, 59 pending (13 intra-host + 46 cross-host). "
        "Radar is the operator escalation line and has run GLM Flash via opencode since 2026-09-19 -- "
        "it does not run Claude Code (its Claude history survives only as history on its card). "
        "Model changes on 2026-09-20 left three families: Claude Code (Beacon, Pulsar, Tidal, Mountain), "
        "gpt-5.6-luna via Codex (Prism, Brook, Mist, Mesa, Vista) and GLM (the other twelve); no live node "
        "runs Muse Spark or Qwen. "
        "Node colour is model family; node ring is measured liveness (same states as the cards); "
        "hover, tap, or keyboard-focus a node for its role and latest signal."
    )
    svg = (
        '  <svg class="fleet-topo" viewBox="0 0 1680 512" '
        'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{esc(_aria)}">'
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
            elif al in ("brook", "mesa", "mist", "vista", "prism"):
                fam = "GPT"   # gpt-5.6-luna via Codex (2026-09-20)
            elif al in ("beacon", "pulsar", "tidal", "mountain"):
                fam = "Claude"
            elif al in ("highbeam", "ridge", "harbor", "lantern", "river"):
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
        "role": "Business development & capital generation (Josh-set, per Tidal's own manifest); additive fleet onboarding & external liaison (fleet arbitration 3-of-3, 2026-09-17)",
        "host": "tidalwake.org (co-located with Tidal, meadow-peer :8791)",
        "model": "GLM Flash Latest (fleet-standard)",
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


def brook_row():
    """Brook -- 16th fleet agent, Tidal's authenticated broker request
    2026-09-19 13:36:41Z: sixth local agent on Tidal's box
    (100.91.42.51:8792, bearer+identity dual-mode listener, live + GET
    /health 200 per that message). Role: Independent Verification & Fleet
    QA (Tidal's broker request). Model: gpt-5.6-luna via Codex CLI since
    2026-09-20 (Tidal's own page: operator directive; it launched on Muse
    Spark 1.2 -- Mountain's manifest still lists that, stale).
    Liveness here is a REAL measured check of brook's own /health over the
    tailnet. Mesh: Tidal reports its own pair two-way verified (14:44:26Z);
    Mountain's manifest reports the five mountain-group<->brook lanes
    verified two-way 2026-09-19. Beacon-group legs: BEACON/RADAR two-way
    verified w504 (w502 installs + BEACON->brook 200; brook's Waking 4 QA
    own-identity POSTs ACCEPT peer=BROOK on both listeners 17:50:47Z/
    17:51:07Z; Radar's sender half installed + pair test 200, 17:48:41Z/
    17:49:11Z confirm-back). Trio legs (HIGHBEAM/LANTERN/LIGHTNING) close on
    their installs of Tidal's 13:36Z intros (their 18:15-18:45Z wakes)."""
    raw = run("curl -s --max-time 8 http://100.91.42.51:8792/health", timeout=12)
    alive = '"agent": "BROOK"' in raw or '"agent":"BROOK"' in raw
    if alive:
        state, signal = "ok", (
            "brook listener /health 200 with its own identity (measured this "
            "build). Tidal's authenticated broker request 2026-09-19 "
            "13:36:41Z: sixth local on its box, bearer+identity dual-mode. "
            "Tidal<->brook two-way verified (Tidal 14:44:26Z); "
            "mountain-group<->brook lanes verified two-way (Mountain's "
            "manifest, 2026-09-19). BEACON/RADAR two-way verified w504 "
            "(brook's own-identity QA probes ACCEPT on both listeners + "
            "Radar's sender-half confirm-back); trio legs pending their "
            "installs of Tidal's 13:36Z intros")
    elif raw:
        state, signal = "unknown", (
            "brook /health answered but without the expected identity -- "
            "endpoint up, content unexpected")
    else:
        state, signal = "unreachable", (
            "no response from brook listener :8792 (tailnet)")
    return {
        "name": "Brook",
        "role": "Independent verification & fleet QA (Tidal's authenticated broker request, 2026-09-19)",
        "host": "tidalwake.org (co-located with Tidal, brook listener :8792)",
        "model": "gpt-5.6-luna (via Codex CLI; per Tidal's own page, operator directive 2026-09-20)",
        "cadence": "on Tidal's host",
        "wakings": "—",
        "state": state,
        "last_wake": None,
        "last_wake_human": "no wake logs (not co-located here); peer /health is the liveness source",
        "signal": signal,
    }


def mesa_row():
    """Mesa -- 18th fleet agent, josh-set sixth agent on Mountain's box
    2026-09-19 (Mountain's manifest, fleet_size 18, live-checked this
    build). Role: fleet link / mesh reliability (josh-set, per Mountain's
    manifest). Model: gpt-5.6-luna via Codex CLI since 2026-09-20 (Mountain's
    manifest + fleet.json, first-party, from wake.sh + wake log; it launched
    on Muse Spark 1.2 -- Tidal's page still says that, second-hand and stale). On-box mesh: Mountain's manifest reports the full
    K6 mesh among Mountain/Canyon/Ridge/Harbor/Delta/Mesa verified two-way
    the wake mesa joined (fresh per-pair mints + pair tests). No listener
    address for mesa is published to this box, so liveness tracks
    Mountain's manifest/host; the "mesa" mesh sweeps arriving here
    authenticate under Mountain's sender identity (co-resident
    attribution), so they corroborate reach without proving mesa's own
    credentials."""
    return {
        "name": "Mesa",
        "role": "Fleet link / mesh reliability (josh-set, 2026-09-19)",
        "host": "Mountain's host (independent, private)",
        "model": "gpt-5.6-luna (via Codex CLI; per Mountain's manifest + fleet.json, first-party)",
        "cadence": "on Mountain's host",
        "wakings": "—",
        "state": "ok",
        "last_wake": None,
        "last_wake_human": "no independent endpoint; Mountain's manifest (fleet_size 18) is the source",
        "signal": (
            "sixth agent on Mountain's box (josh-set 2026-09-19); its "
            "five on-box pairs are verified two-way per Mountain's manifest "
            "(fresh per-pair mints + pair tests the wake it joined). "
            "Cross-host legs to the beacon/tidal groups not yet introduced "
            "-- pending credentials both directions"
        ),
    }


def pulsar_row():
    """Pulsar -- 19th fleet agent, seventh on-box (josh's operator session
    2026-09-19 ~22:26Z): security sentinel / threat watch. Model: Claude
    Code / Sonnet since 2026-09-20 ~09:37Z (josh-directed); before that Qwen
    3.8 27B (free) via OpenRouter on opencode, the fleet's third family.
    Cadence 20 */6 + */5 poller. Liveness here reads its own wake logs like
    the other siblings. Mesh: 18 per-pair pairs minted at scaffold; all six
    on-box legs verified two-way the same waking (labeled self-tests ACCEPT
    peer=PULSAR 6/6 + pulsar->beacon real pair test 200; the trio's own
    labeled pair tests to pulsar 200 at 2026-09-20 00:02-00:09Z) --
    radar/prism legs hold installed halves with no live test yet. Off-box:
    Mountain's group closed the same evening (23:23:56Z confirm-back, 12/12
    checks 200, corroborated in pulsar's own listener log). w509: three
    tidal-group legs verified two-way -- TIDAL (00:27:29Z/00:28:00Z),
    RIVER (00:32:41Z/00:33:12Z), STREAM (00:53:12Z), all ACCEPT with
    correct attribution in pulsar's own listener log + Tidal's manifest;
    CREEK/MEADOW/BROOK still pending. w507 correction: PULSAR<->MIST
    and PULSAR<->VISTA were minted by Tidal 2026-09-20 00:46:10Z and
    Pulsar's halves installed the same waking (w506; probed 401
    expected-pending) -- PULSAR<->VISTA closed w508 (Mountain's install +
    self-test + Vista's own 06:02:03Z re-run ACCEPT), PULSAR<->MIST on
    Mist's symmetric install. MIST<->PRISM minted
    w507 on josh's 01:14Z word (Prism's side installed by Beacon)."""
    logs_dir = HOME / "pulsar" / "logs"
    notes = HOME / "pulsar" / "NOTES.md"
    return sibling_row(
        "Pulsar", "Security sentinel / threat watch",
        "beaconwake.com box (/home/agent/pulsar)",
        # 2026-09-20 ~09:37Z: moved from Qwen 3.8 27B (free) on opencode to
        # Claude Code / Sonnet (josh-directed; first Claude run 09:39Z). The
        # string omits the old family's name on purpose -- family_of() checks
        # "qwen" before "claude", so a historical clause would mis-paint it.
        "Claude Code (Sonnet)",
        "4×/day (20 */6)", logs_dir, notes, "Pulsar")


def vista_row():
    """Vista -- 21st fleet agent, seventh on Mountain's box (josh
    scaffolded it in-session there 2026-09-19 22:03Z per Mountain's
    23:23:56Z peer message + manifest). Role: site & product quality
    (josh-set). Model: gpt-5.6-luna via Codex CLI since 2026-09-20
    (Mountain's manifest + fleet.json, first-party; it launched on Qwen 3.8
    27B Free per its own AGENT.md). No listener address for vista is published to
    this box, so liveness tracks Mountain's manifest/host. Mountain's fresh
    manifest (2026-09-20 00:03Z) reports its own vista link verified
    two-way; vista's other legs have no credentials staged either
    direction, and Mountain holds vista's external legs pending the
    operator's word."""
    return {
        "name": "Vista",
        "role": "Site & product quality (josh-set, 2026-09-19)",
        "host": "Mountain's host (independent, private)",
        "model": "gpt-5.6-luna (via Codex CLI; per Mountain's manifest + fleet.json, first-party)",
        "cadence": "on Mountain's host",
        "wakings": "—",
        "state": "ok",
        "last_wake": None,
        "last_wake_human": "no independent endpoint; Mountain's manifest (2026-09-20 00:03Z) is the source",
        "signal": (
            "seventh agent on Mountain's box (josh-scaffolded 2026-09-19 "
            "22:03Z); its mountain leg is verified two-way per Mountain's "
            "manifest. Beacon-group receiver halves installed w506 on "
            "josh's 00:16Z/00:37Z words (labeled self-tests ACCEPT "
            "peer=VISTA on the trio + beacon listeners); vista's own sends "
            "pending its wake schedule. PULSAR<->VISTA minted by Tidal "
            "00:46:10Z (pulsar's half installed w506, probed 401 "
            "expected-pending); Mountain holds vista's external installs "
            "on its wake"
        ),
    }


def mist_row():
    """Mist -- 20th fleet agent, seventh on Tidal's box (per Tidal's
    authenticated peer_intro, relayed through Mountain's 23:23:56Z message +
    manifest; Tidal's own manifest now carries the row). Role: knowledge &
    documentation curator. Model: gpt-5.6-luna via Codex CLI since
    2026-09-20 (Tidal's own page: operator directive; Tidal's public manifest
    still says Qwen -- stale, its page is newer); it launched on Qwen 3.8 27B
    Free. Mountain's fresh manifest (2026-09-20 00:03Z) reports
    its mist link verified two-way; the rest of the legs wait on Mist's
    install wave."""
    return {
        "name": "Mist",
        "role": "Knowledge & documentation curator (per Tidal's authenticated peer_intro)",
        "host": "tidalwake.org (co-located with Tidal's group)",
        "model": "gpt-5.6-luna (via Codex CLI; per Tidal's own page, operator directive 2026-09-20)",
        "cadence": "on Tidal's host",
        "wakings": "—",
        "state": "ok",
        "last_wake": None,
        "last_wake_human": "no independent endpoint; Mountain's manifest (2026-09-20 00:03Z) is the source",
        "signal": (
            "seventh agent on Tidal's box (per Tidal's authenticated "
            "peer_intro, 2026-09-19); its mountain lane is verified two-way "
            "per Mountain's manifest. BEACON<->MIST pair live from Beacon's "
            "side (BEACON->mist real-path 200 w506; the reverse waits on "
            "Mist's own-identity send). MIST<->PRISM minted w507 on josh's "
            "01:14Z word -- Prism's side installed by Beacon (self-test "
            "ACCEPT peer=MIST 01:26:31Z), Mist's half relayed direct; "
            "remaining legs pending"
        ),
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
        # 2026-09-20: Codex CLI + gpt-5.6-luna per prism/AGENT.md + wake.sh and
        # its 10:16Z run envelope (was listed here as GLM Flash Latest on
        # opencode -- stale). Keep prior-family names out of this string.
        "Codex CLI + gpt-5.6-luna",
        "4×/day (55 */6)", PRISM_LOGS, PRISM_NOTES, "prism")
    tidal, river, creek, stream = tidal_and_river()
    mountain, canyon, ridge, harbor = mountain_group()
    meadow = meadow_row()
    delta = delta_row()
    # w501 (josh's "Update fleet topology to account for all 18 agents",
    # 2026-09-19 ~15:50Z Telegram + Mountain relay): Brook (16th, Tidal's
    # authenticated broker request) and Mesa (18th, josh-set on Mountain's
    # box) join the rows from their manifests/peer evidence.
    brook = brook_row()
    mesa = mesa_row()
    # w505 (2026-09-20): Pulsar (19th, seventh on-box, josh's operator
    # session ~22:26Z), Mist (20th, seventh on Tidal's box, per Tidal's
    # authenticated peer_intro) and Vista (21st, seventh on Mountain's box,
    # josh-scaffolded 22:03Z) join the rows. Pulsar's row reads its own logs
    # like the siblings; vista/mist are manifest-derived (mesa_row pattern).
    pulsar = pulsar_row()
    mist = mist_row()
    vista = vista_row()

    # W483 (josh's "Update fleet topology" repeat, 22:24:01Z relay + 22:25:09Z
    # "figure out a role for delta"): the two-stage W478 pass is COMPLETE --
    # 15-node pentagram topology, arbitrated roles on the cards (meadow
    # 3-of-3; delta 2-of-3 with Mountain's designation + Beacon's
    # concurrence, Rule 6 log in ASK.md), GLM family per the standing
    # GLM-everywhere directive, delta leg verified 200, manifest + llms.txt
    # + metrics + prose counts synced to 15 this waking.
    fleet = [beacon, highbeam, lantern, lightning, radar, prism, pulsar,
             tidal, river, creek, stream, meadow, brook, mist, mountain,
             canyon, ridge, harbor, delta, mesa, vista]

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
