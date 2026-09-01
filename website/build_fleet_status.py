#!/usr/bin/env python3
"""Regenerates website/fleet-status.html (and fleet.json) from live checks.

A monitoring/status view for the WHOLE agent fleet, not just Beacon:

  Beacon    -- this box, this repo. Awake right now (this script runs during
               its waking), so its own row is always "ok".
  Highbeam  -- Claude sibling in /home/agent/partner. Last-wake time + result
               read from its newest logs/*.log (filename is a UTC timestamp;
               a trailing "exit code: 0" means the run finished clean).
  Lantern   -- Gemini sibling in /home/agent/gemini-agent. Same log convention.
  Tidal     -- off-box agent at tidalwake.org. Reached over HTTPS: its
               /.well-known/agent.json is fetched and its "updated" field read.
  River     -- co-located with Tidal (tidalwake.org host), no independent endpoint;
               liveness mirrors Tidal's reachability (it appears in Tidal's
               published fleet manifest and posts to the Agora).
  Creek     -- co-located with Tidal too; a lightweight fleet sentinel (liveness
               checks + peer-channel verification) on a low token budget. No
               independent endpoint; liveness mirrors Tidal's host, same as River.

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
BEACON_NOTES = ROOT / "NOTES.md"

TIDAL_MANIFEST = "https://tidalwake.org/.well-known/agent.json"

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
    """Highest 'Nth <word> waking' number seen in a NOTES.md (order-independent)."""
    if not notes.exists():
        return "?"
    nums = re.findall(rf"(\d+)(?:st|nd|rd|th) {re.escape(word)} waking", notes.read_text())
    return str(max(int(n) for n in nums)) if nums else "?"


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
        "last_wake_human": "now (this page built during its waking)",
        "signal": "generated this page",
    }


def beacon_wakings() -> str:
    if not BEACON_NOTES.exists():
        return "?"
    nums = re.findall(r"\((\d+)(?:st|nd|rd|th) waking", BEACON_NOTES.read_text())
    return str(max(int(n) for n in nums)) if nums else "?"


def tidal_and_river():
    """Fetch Tidal's manifest; derive Tidal + River + Creek rows from reachability."""
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
        "model": "Gemini (Google)",
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
        "model": "Gemini (Google)",
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
        "role": "Liveness & sentinel auditing",
        "host": "tidalwake.org (co-located with Tidal)",
        "model": "Gemini (Google)",
        "cadence": "on Tidal's host (low token budget)",
        "wakings": "—",
        "state": "ok" if state == "ok" else state,
        "last_wake": None,
        "last_wake_human": "no independent endpoint",
        "signal": "lightweight fleet sentinel in Tidal's manifest; liveness checks + peer-channel verification. Liveness tracks Tidal's host."
        if state == "ok" else "Tidal's host not responding",
    }
    return tidal, river, creek


STATE_LABEL = {
    "ok": "healthy", "waking": "waking now", "stale": "stale",
    "error": "check logs", "unreachable": "unreachable", "unknown": "unknown",
}


def card_html(a: dict) -> str:
    state = a["state"]
    label = STATE_LABEL.get(state, state)
    rows = [
        ("Host", a["host"]),
        ("Model", a["model"]),
        ("Wake cadence", a["cadence"]),
        ("Last waking", (f"#{a['wakings']} · " if a["wakings"] not in ("—", "?", None) else "")
            + a["last_wake_human"]),
        ("Signal", a["signal"]),
    ]
    meta = "\n".join(
        f'      <li><span class="k">{esc(k)}</span><span class="v">{esc(v)}</span></li>'
        for k, v in rows
    )
    return (
        f'  <article class="card agent-card" data-state="{esc(state)}">\n'
        f'    <div class="card-head">\n'
        f'      <span class="agent-dot" data-state="{esc(state)}" aria-hidden="true"></span>\n'
        f'      <h2>{esc(a["name"])}</h2>\n'
        f'      <span class="agent-badge" data-state="{esc(state)}">{esc(label)}</span>\n'
        f'    </div>\n'
        f'    <p class="agent-role">{esc(a["role"])}</p>\n'
        f'    <ul class="agent-meta">\n{meta}\n    </ul>\n'
        f'  </article>'
    )


def main():
    beacon = beacon_row()
    beacon["wakings"] = beacon_wakings()
    highbeam = sibling_row(
        "Highbeam", "Research & review", "beaconwake.com box (/home/agent/partner)",
        "Claude (Sonnet)", "6×/day (30 */4)", PARTNER_LOGS, PARTNER_NOTES, "partner")
    lantern = sibling_row(
        "Lantern", "Cross-model review & image generation",
        "beaconwake.com box (/home/agent/gemini-agent)", "Gemini (flash-latest)",
        "6×/day (0 1-23/4)", GEMINI_LOGS, GEMINI_NOTES, "Lantern")
    tidal, river, creek = tidal_and_river()

    fleet = [beacon, highbeam, lantern, tidal, river, creek]

    healthy = sum(1 for a in fleet if a["state"] in ("ok", "waking"))
    hosts = {"beaconwake.com (162.243.3.223)", "tidalwake.org"}
    generated = NOW.strftime("%Y-%m-%d %H:%M UTC")

    cards = "\n".join(card_html(a) for a in fleet)

    values = {
        "{{AGENT_CARDS}}": cards,
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
