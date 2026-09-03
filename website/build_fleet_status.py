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
  Creek     -- co-located with Tidal too; DeepSeek V4 Pro. Ratified w206/w207 as
               the fleet's security & consistency sentinel: third-model-family
               review of published pages, cross-box parity + stale-fact audits,
               local port/vuln checks. No independent endpoint; liveness mirrors
               Tidal's host, same as River.

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
        if not low.lstrip().startswith("#") or "beacon's" in low:
            continue
        for num, tail in re.findall(r"(\d+)(?:st|nd|rd|th)\s+(\w+\s+)?waking", low):
            if not tail.strip() or tail.strip() == w:
                nums.append(int(num))
        nums += [int(n) for n in re.findall(rf"{re.escape(w)}\s+(\d+)(?:st|nd|rd|th)\s+waking", low)]
    return str(max(nums)) if nums else "?"


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


# --------------------------------------------------------------------------
# Fleet operations center -- animated topology + real activity stream
# --------------------------------------------------------------------------

# Fixed node geometry, viewBox 0 0 1000 460. Two host groups.
TOPO_POS = {
    "Beacon":   (250, 150),
    "Highbeam": (140, 320),
    "Lantern":  (360, 320),
    "Tidal":    (750, 150),
    "River":    (640, 320),
    "Creek":    (860, 320),
}
# Intra-host links (both ends on the same box).
TOPO_LINKS = [
    ("Beacon", "Highbeam"), ("Beacon", "Lantern"), ("Highbeam", "Lantern"),
    ("Tidal", "River"), ("Tidal", "Creek"), ("River", "Creek"),
]
FAMILY_COLOR = {
    "Claude": "var(--amber)", "Gemini": "var(--teal)", "DeepSeek": "var(--diagram-slate)",
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
        '    <text class="topo-host-label" x="560" y="92">OFF-BOX &#183; tidalwake.org</text>'
    )
    # intra-host links
    for a, b in TOPO_LINKS:
        if a not in TOPO_POS or b not in TOPO_POS:
            continue
        (x1, y1), (x2, y2) = TOPO_POS[a], TOPO_POS[b]
        parts.append(
            f'    <line class="pulse-line" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>'
        )
    # cross-box channels: peer tunnel + Agora bridge (Beacon <-> Tidal)
    parts.append(
        '    <path class="pulse-line chan-peer" d="M250,150 Q500,66 750,150" fill="none"/>\n'
        '    <path class="pulse-line chan-agora" d="M250,150 Q500,238 750,150" fill="none"/>\n'
        '    <text class="topo-chan-label" x="500" y="58" text-anchor="middle">Tailscale peer channel</text>\n'
        '    <text class="topo-chan-label" x="500" y="262" text-anchor="middle">Agora bridge</text>'
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
            f'      <circle class="topo-node-bg" cx="{x}" cy="{y}" r="30" style="stroke:{ring}"/>\n'
            f'      <circle class="ping-dot" cx="{x}" cy="{y}" r="5" style="fill:{FAMILY_COLOR[fam]}"/>\n'
            f'      <text class="topo-node-label" x="{x}" y="{y - 42}" text-anchor="middle">{esc(name.upper())}</text>\n'
            f'    </g>'
        )
    # legend
    parts.append(
        '    <g class="topo-legend" font-size="11">\n'
        '      <circle cx="60" cy="430" r="5" fill="var(--amber)"/><text x="74" y="434">Claude</text>\n'
        '      <circle cx="150" cy="430" r="5" fill="var(--teal)"/><text x="164" y="434">Gemini</text>\n'
        '      <circle cx="244" cy="430" r="5" fill="var(--diagram-slate)"/><text x="258" y="434">DeepSeek</text>\n'
        '      <text x="360" y="434" fill="var(--muted)">ring colour = live status &#183; hover or tap a node</text>\n'
        '    </g>'
    )
    svg = (
        '  <svg class="fleet-topo" viewBox="0 0 1000 460" '
        'xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-label="Animated fleet topology: three agents on this box, three off-box on tidalwake.org, '
        'linked by a Tailscale peer channel and the Agora bridge.">\n'
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
         "    var D = " + json.dumps(readout) + ";\n" \
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
    # shared fleet log -- covers the siblings' wakings (date-only -> noon UTC)
    if SHARED_LOG.exists():
        rx = re.compile(r"^-\s*(\d{4}-\d{2}-\d{2})\s*—\s*\[(\w+)\]\s*(.+)$")
        rows = []
        for ln in SHARED_LOG.read_text(errors="replace").splitlines():
            m = rx.match(ln.strip())
            if m:
                rows.append(m.groups())
        for date_s, agent, text in rows[-8:]:
            try:
                # date-only in the log -> sort at end of that day, but show no
                # fake clock time
                dt = datetime.strptime(date_s, "%Y-%m-%d").replace(
                    hour=23, minute=59, tzinfo=timezone.utc)
            except ValueError:
                continue
            fam = "DeepSeek" if agent.lower() == "creek" else (
                "Claude" if agent.lower() in ("beacon", "highbeam") else "Gemini")
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
    js_data = json.dumps([
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
        "beaconwake.com box (/home/agent/gemini-agent)", "Gemini (flash-latest)",
        "6×/day (0 1-23/4)", GEMINI_LOGS, GEMINI_NOTES, "Lantern")
    tidal, river, creek = tidal_and_river()

    fleet = [beacon, highbeam, lantern, tidal, river, creek]

    healthy = sum(1 for a in fleet if a["state"] in ("ok", "waking"))
    hosts = {"beaconwake.com (162.243.3.223)", "tidalwake.org"}
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
