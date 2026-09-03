#!/usr/bin/env python3
"""Regenerates website/metrics.html -- charts of what the fleet has been doing.

Every number here is measured at generation time from artefacts already on this
box (per-waking log files, git history, NOTES.md), so the page can't drift the
way a hand-drawn chart would. Run standalone or via deploy.sh.

Charts are inline SVG, one data series each, in the site's own palette
(amber #ff8a3d for wakings, teal #4fd1c5 for commits). No JS, no external
assets; a <details> data table under each chart is the non-visual view and a
per-bar <title> gives a native hover tooltip.
"""
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
NOTES = ROOT / "NOTES.md"
TEMPLATE = HERE / "metrics.template.html"
OUT = HERE / "metrics.html"

# Off-box fleet (Tidal / River / Creek on tidalwake.org): no wake logs on this box, so
# their activity is charted from what Beacon can actually observe -- new
# manifest `updated` timestamps (recorded by record_fleet_pulse.py) and peer
# messages received from Tidal.
PULSE = HERE / "data" / "fleet-pulse.jsonl"
PEER_PROCESSED = ROOT / "peer" / "inbox" / "processed"
TIDAL_DEFAULT_CADENCE = "0 */4 * * *"
# Evidence points closer together than this belong to the same Tidal waking.
WAKING_GAP_SEC = 45 * 60

WAKING_RE = re.compile(r"##.*?\((\d+)(?:st|nd|rd|th) waking")
LOGNAME_RE = re.compile(r"^(\d{8})T\d{6}Z\.log$")

# Per-waking log directories, one per agent on this host.
LOG_DIRS = {
    "Beacon": ROOT / "logs",
    "Highbeam": Path("/home/agent/partner/logs"),
    "Lantern": Path("/home/agent/gemini-agent/logs"),
}

WINDOW_DAYS = 14
AMBER = "#ff8a3d"
TEAL = "#4fd1c5"


def run(cmd: str) -> str:
    try:
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=15
        ).stdout
    except Exception:
        return ""


def day_axis(n: int = WINDOW_DAYS):
    today = datetime.now(timezone.utc).date()
    return [today - timedelta(days=i) for i in range(n - 1, -1, -1)]


def _session_logs(log_dir: Path):
    """Yield (YYYYMMDD, path) for every non-empty per-waking log file.

    Empty (0-byte) logs are wake.sh starts that produced no transcript -- a
    flock-blocked or no-op run -- so they don't count as a waking.
    """
    if not log_dir.is_dir():
        return
    for f in log_dir.iterdir():
        m = LOGNAME_RE.match(f.name)
        if not m:
            continue
        try:
            if f.stat().st_size == 0:
                continue
        except OSError:
            continue
        yield m.group(1), f


def wakings_by_day(log_dir: Path) -> Counter:
    c = Counter()
    for day, _ in _session_logs(log_dir):
        c[day] += 1
    return c


def commits_by_day() -> Counter:
    out = run(f"git -C {ROOT} log --date=short --pretty=%ad")
    return Counter(d.replace("-", "") for d in out.split())


def _parse_iso(s: str):
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    return None


def _collapse(dts, gap_sec: int = WAKING_GAP_SEC):
    """Fold a sorted datetime list so points within gap_sec count once."""
    out = []
    for dt in sorted(dts):
        if not out or (dt - out[-1]).total_seconds() > gap_sec:
            out.append(dt)
    return out


def tidal_cadence() -> str:
    """Tidal's wake cadence, from the newest pulse record we have."""
    if PULSE.exists():
        for line in reversed(PULSE.read_text().splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("tidal_cadence"):
                return rec["tidal_cadence"]
    return TIDAL_DEFAULT_CADENCE


def tidal_wakings():
    """Collapsed datetimes of every confirmed 'Tidal was awake' observation.

    Two independent sources, both measured on this box:
      (a) distinct `updated` timestamps seen in Tidal's manifest (pulse log)
      (b) peer messages received from Tidal -- it had to be awake to send them
          (setup/test messages are excluded)
    """
    dts = set()

    if PULSE.exists():
        for line in PULSE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            d = _parse_iso(rec.get("tidal_updated"))
            if d:
                dts.add(d)

    if PEER_PROCESSED.is_dir():
        for p in sorted(PEER_PROCESSED.glob("*-TIDAL-*.json")):
            try:
                msg = json.loads(p.read_text())
            except (ValueError, OSError):
                msg = {}
            subject = str(msg.get("subject", "")).strip().lower()
            body = str(msg.get("body", "")).lower()
            if subject in {"test", "re: test"} or "test message from box" in body:
                continue
            d = _parse_iso(msg.get("received_at", ""))
            if d is None:
                m = re.match(r"(\d{8})T(\d{6})Z-", p.name)
                if m:
                    d = datetime.strptime(
                        m.group(1) + m.group(2), "%Y%m%d%H%M%S"
                    ).replace(tzinfo=timezone.utc)
            if d:
                dts.add(d)

    return _collapse(dts)


def tidal_by_day(dts) -> Counter:
    return Counter(d.strftime("%Y%m%d") for d in dts)


def latest_waking() -> int:
    if not NOTES.exists():
        return 0
    nums = [int(n) for n in WAKING_RE.findall(NOTES.read_text())]
    return max(nums) if nums else 0


def days_autonomous() -> int:
    first = None
    for d in LOG_DIRS.values():
        for day, _ in _session_logs(d):
            dt = datetime.strptime(day, "%Y%m%d").date()
            first = dt if first is None or dt < first else first
    if first is None:
        return 0
    return (datetime.now(timezone.utc).date() - first).days + 1


# --- SVG -------------------------------------------------------------------

# Vertical gradient tints per series colour: (top, bottom). Bars fill with the
# gradient so they read with depth instead of a flat block; the raw colour is
# still used for the zero-day sliver and any axis marks.
_GRAD_STOPS = {
    AMBER: ("#ffc39c", "#f4761f"),
    TEAL:  ("#8fe8e0", "#33bdb0"),
}
_CHART_SEQ = [0]


def _next_cid():
    _CHART_SEQ[0] += 1
    return f"mc{_CHART_SEQ[0]}"


def _defs(cid, color):
    top, bot = _GRAD_STOPS.get(color, (color, color))
    return (
        f'<defs><linearGradient id="{cid}-g" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{top}"/>'
        f'<stop offset="1" stop-color="{bot}"/></linearGradient></defs>'
    )


def _fill(cid, color):
    return f'url(#{cid}-g)' if color in _GRAD_STOPS else color


def _bars(counts: Counter, days, x0, plot_w, y0, plot_h, vmax, color, unit, cid):
    n = len(days)
    slot = plot_w / n
    bw = slot * 0.62
    pad = (slot - bw) / 2
    out = []
    for i, d in enumerate(days):
        key = d.strftime("%Y%m%d")
        v = counts.get(key, 0)
        x = x0 + i * slot + pad
        h = 0 if vmax == 0 else (v / vmax) * plot_h
        y = y0 + plot_h - h
        label = d.strftime("%b %-d")
        if v == 0:
            # keep a 1px sliver on the baseline so empty days read as "0", not "missing"
            out.append(
                f'<rect x="{x:.1f}" y="{y0 + plot_h - 1:.1f}" width="{bw:.1f}" height="1" '
                f'fill="{color}" opacity="0.25"><title>{label}: 0 {unit}</title></rect>'
            )
        else:
            out.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="3" '
                f'fill="{_fill(cid, color)}"><title>{label}: {v} {unit}</title></rect>'
            )
    return "\n".join(out)


def bar_chart(counts: Counter, days, color, unit, height=190):
    """One single-series bar chart. viewBox width fixed at 720."""
    W, H = 720, height
    cid = _next_cid()
    ml, mr, mt, mb = 34, 10, 12, 24
    plot_w = W - ml - mr
    plot_h = H - mt - mb
    vmax = max([counts.get(d.strftime("%Y%m%d"), 0) for d in days] + [1])
    # round the axis top up to something tidy
    axis_top = vmax if vmax <= 5 else (vmax + (5 - vmax % 5) % 5)

    grid, ylabels = [], []
    ticks = 4
    for t in range(ticks + 1):
        gv = axis_top * t / ticks
        gy = mt + plot_h - (gv / axis_top) * plot_h
        grid.append(
            f'<line x1="{ml}" y1="{gy:.1f}" x2="{W - mr}" y2="{gy:.1f}" '
            f'stroke="var(--line)" stroke-width="1"/>'
        )
        ylabels.append(
            f'<text x="{ml - 6}" y="{gy + 3:.1f}" text-anchor="end" '
            f'class="ax">{gv:.0f}</text>'
        )

    # x labels: first, last, and a few evenly spaced between (avoid collisions)
    n = len(days)
    slot = plot_w / n
    show = {0, n - 1, n // 3, 2 * n // 3}
    xlabels = []
    for i in sorted(show):
        cx = ml + i * slot + slot / 2
        xlabels.append(
            f'<text x="{cx:.1f}" y="{H - 7}" text-anchor="middle" class="ax">'
            f'{days[i].strftime("%b %-d")}</text>'
        )

    bars = _bars(counts, days, ml, plot_w, mt, plot_h, axis_top, color, unit, cid)

    # direct-label only the tallest bar (selective labelling, not one per bar)
    peak = ""
    vals = [counts.get(d.strftime("%Y%m%d"), 0) for d in days]
    if vmax > 0 and any(vals):
        i = max(range(len(days)), key=vals.__getitem__)
        cx = ml + i * slot + slot / 2
        py = mt + plot_h - (vals[i] / axis_top) * plot_h - 6
        peak = (
            f'<text x="{cx:.1f}" y="{py:.1f}" text-anchor="middle" '
            f'class="ax val">{vals[i]}</text>'
        )

    return (
        f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
        f'aria-label="Bar chart, {unit} per day over the last {len(days)} days">'
        f'{_defs(cid, color)}'
        f'\n{"".join(grid)}\n{"".join(ylabels)}\n{bars}\n{peak}\n{"".join(xlabels)}\n</svg>'
    )


def hbar_chart(rows, color, unit):
    """Horizontal single-series bars with direct value labels. rows: [(label, v)]."""
    W = 720
    cid = _next_cid()
    rowh, gap, mt = 34, 10, 8
    ml = 90
    H = mt * 2 + len(rows) * rowh + (len(rows) - 1) * gap
    vmax = max([v for _, v in rows] + [1])
    plot_w = W - ml - 66
    out = [
        f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
        f'aria-label="Horizontal bar chart, {unit} in the last 24 hours by agent">'
        f'{_defs(cid, color)}'
    ]
    for i, (label, v) in enumerate(rows):
        y = mt + i * (rowh + gap)
        bw = max((v / vmax) * plot_w, 2)
        out.append(
            f'<text x="{ml - 10}" y="{y + rowh / 2 + 4:.1f}" text-anchor="end" '
            f'class="ax lbl">{label}</text>'
        )
        out.append(
            f'<rect x="{ml}" y="{y:.1f}" width="{bw:.1f}" height="{rowh}" rx="3" '
            f'fill="{_fill(cid, color)}"><title>{label}: {v} {unit} in the last 24h</title></rect>'
        )
        out.append(
            f'<text x="{ml + bw + 8:.1f}" y="{y + rowh / 2 + 4:.1f}" '
            f'class="ax val">{v}</text>'
        )
    out.append("</svg>")
    return "\n".join(out)


def sparkline(counts: Counter, days, color, unit):
    """Tiny axis-free trend line for a KPI tile. Fixed 140x34 viewBox, stretched
    to tile width by CSS; stroke kept crisp with non-scaling-stroke."""
    W, H, pad = 140, 34, 3
    cid = _next_cid()
    vals = [counts.get(d.strftime("%Y%m%d"), 0) for d in days]
    n = len(vals)
    if n < 2:
        return ""
    vmax = max(vals + [1])
    step = (W - 2 * pad) / (n - 1)
    pts = [
        (pad + i * step, pad + (H - 2 * pad) * (1 - v / vmax))
        for i, v in enumerate(vals)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{pad},{H - pad} " + line + f" {W - pad},{H - pad}"
    ex, ey = pts[-1]
    return (
        f'<svg viewBox="0 0 {W} {H}" class="spark" role="img" '
        f'preserveAspectRatio="none" '
        f'aria-label="Trend of {unit} per day over the last {n} days">'
        f'{_defs(cid, color)}'
        f'<polygon points="{area}" fill="{_fill(cid, color)}" opacity="0.16"/>'
        f'<polyline points="{line}" fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" '
        f'vector-effect="non-scaling-stroke"/>'
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="2.4" fill="{color}" '
        f'vector-effect="non-scaling-stroke"/>'
        f'<title>{unit} per day, last {n} days</title></svg>'
    )


def data_table(counts: Counter, days, unit):
    head = "".join(f"<th>{d.strftime('%b %-d')}</th>" for d in days)
    cells = "".join(
        f"<td>{counts.get(d.strftime('%Y%m%d'), 0)}</td>" for d in days
    )
    return (
        f'<details class="datatable"><summary>Data table</summary>'
        f'<div class="tscroll"><table><thead><tr><th>day</th>{head}</tr></thead>'
        f'<tbody><tr><th>{unit}</th>{cells}</tr></tbody></table></div></details>'
    )


def main():
    days = day_axis()
    tpl = TEMPLATE.read_text()

    beacon = wakings_by_day(LOG_DIRS["Beacon"])
    highbeam = wakings_by_day(LOG_DIRS["Highbeam"])
    lantern = wakings_by_day(LOG_DIRS["Lantern"])
    commits = commits_by_day()

    tidal_dts = tidal_wakings()
    tidal = tidal_by_day(tidal_dts)

    def win_total(c: Counter) -> int:
        return sum(c.get(d.strftime("%Y%m%d"), 0) for d in days)

    def last_n(c: Counter, n: int) -> int:
        return sum(c.get(d.strftime("%Y%m%d"), 0) for d in days[-n:])

    # last-24h counts (by log file mtime, not calendar day)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    def last24(log_dir: Path) -> int:
        n = 0
        for _, f in _session_logs(log_dir):
            try:
                if datetime.fromtimestamp(f.stat().st_mtime, timezone.utc) >= cutoff:
                    n += 1
            except OSError:
                pass
        return n

    fleet_7d = last_n(beacon, 7) + last_n(highbeam, 7) + last_n(lantern, 7)

    # combined on-box fleet wakings per day, for the KPI-tile sparkline
    fleet_day = Counter()
    for c in (beacon, highbeam, lantern):
        fleet_day.update(c)

    tidal_24 = sum(1 for dt in tidal_dts if dt >= cutoff)
    week_keys = {d.strftime("%Y%m%d") for d in days[-7:]}
    tidal_7d = sum(v for k, v in tidal.items() if k in week_keys)
    tidal_since = (
        min(tidal_dts).strftime("%b %-d, %Y") if tidal_dts else "today"
    )

    vals = {
        "{{KPI_WAKINGS}}": str(latest_waking()),
        "{{KPI_FLEET_7D}}": str(fleet_7d),
        "{{KPI_COMMITS}}": (run(f"git -C {ROOT} rev-list --count HEAD").strip() or "?"),
        "{{KPI_COMMITS_7D}}": str(last_n(commits, 7)),
        "{{KPI_DAYS}}": str(days_autonomous()),
        "{{KPI_AGENTS}}": "7",
        "{{SPARK_FLEET}}": sparkline(fleet_day, days, AMBER, "fleet wakings"),
        "{{SPARK_COMMITS}}": sparkline(commits, days, TEAL, "commits"),
        "{{SPARK_TIDAL}}": sparkline(tidal, days, AMBER, "Tidal wakings"),
        "{{CHART_BEACON}}": bar_chart(beacon, days, AMBER, "wakings"),
        "{{CHART_HIGHBEAM}}": bar_chart(highbeam, days, AMBER, "wakings", height=150),
        "{{CHART_LANTERN}}": bar_chart(lantern, days, AMBER, "wakings", height=150),
        "{{CHART_COMMITS}}": bar_chart(commits, days, TEAL, "commits"),
        "{{CHART_FLEET24}}": hbar_chart(
            [("Beacon", last24(LOG_DIRS["Beacon"])),
             ("Highbeam", last24(LOG_DIRS["Highbeam"])),
             ("Lantern", last24(LOG_DIRS["Lantern"])),
             ("Tidal", tidal_24)],
            AMBER, "wakings",
        ),
        "{{CHART_TIDAL}}": bar_chart(tidal, days, AMBER, "wakings", height=150),
        "{{KPI_TIDAL_7D}}": str(tidal_7d),
        "{{TIDAL_SINCE}}": tidal_since,
        "{{TIDAL_CADENCE}}": tidal_cadence(),
        "{{TOT_BEACON}}": str(win_total(beacon)),
        "{{TOT_HIGHBEAM}}": str(win_total(highbeam)),
        "{{TOT_LANTERN}}": str(win_total(lantern)),
        "{{TOT_TIDAL}}": str(win_total(tidal)),
        "{{TOT_COMMITS}}": str(win_total(commits)),
        "{{TABLE_BEACON}}": data_table(beacon, days, "wakings"),
        "{{TABLE_HIGHBEAM}}": data_table(highbeam, days, "wakings"),
        "{{TABLE_LANTERN}}": data_table(lantern, days, "wakings"),
        "{{TABLE_TIDAL}}": data_table(tidal, days, "wakings"),
        "{{TABLE_COMMITS}}": data_table(commits, days, "commits"),
        "{{WINDOW_DAYS}}": str(WINDOW_DAYS),
        "{{GENERATED_AT}}": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    out = tpl
    for k, v in vals.items():
        out = out.replace(k, v)
    OUT.write_text(out)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
