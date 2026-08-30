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

def _bars(counts: Counter, days, x0, plot_w, y0, plot_h, vmax, color, unit):
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
                f'fill="{color}"><title>{label}: {v} {unit}</title></rect>'
            )
    return "\n".join(out)


def bar_chart(counts: Counter, days, color, unit, height=190):
    """One single-series bar chart. viewBox width fixed at 720."""
    W, H = 720, height
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

    bars = _bars(counts, days, ml, plot_w, mt, plot_h, axis_top, color, unit)

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
        f'\n{"".join(grid)}\n{"".join(ylabels)}\n{bars}\n{peak}\n{"".join(xlabels)}\n</svg>'
    )


def hbar_chart(rows, color, unit):
    """Horizontal single-series bars with direct value labels. rows: [(label, v)]."""
    W = 720
    rowh, gap, mt = 34, 10, 8
    ml = 90
    H = mt * 2 + len(rows) * rowh + (len(rows) - 1) * gap
    vmax = max([v for _, v in rows] + [1])
    plot_w = W - ml - 66
    out = [
        f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
        f'aria-label="Horizontal bar chart, {unit} in the last 24 hours by agent">'
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
            f'fill="{color}"><title>{label}: {v} {unit} in the last 24h</title></rect>'
        )
        out.append(
            f'<text x="{ml + bw + 8:.1f}" y="{y + rowh / 2 + 4:.1f}" '
            f'class="ax val">{v}</text>'
        )
    out.append("</svg>")
    return "\n".join(out)


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

    vals = {
        "{{KPI_WAKINGS}}": str(latest_waking()),
        "{{KPI_FLEET_7D}}": str(fleet_7d),
        "{{KPI_COMMITS}}": (run(f"git -C {ROOT} rev-list --count HEAD").strip() or "?"),
        "{{KPI_COMMITS_7D}}": str(last_n(commits, 7)),
        "{{KPI_DAYS}}": str(days_autonomous()),
        "{{KPI_AGENTS}}": "5",
        "{{CHART_BEACON}}": bar_chart(beacon, days, AMBER, "wakings"),
        "{{CHART_HIGHBEAM}}": bar_chart(highbeam, days, AMBER, "wakings", height=150),
        "{{CHART_LANTERN}}": bar_chart(lantern, days, AMBER, "wakings", height=150),
        "{{CHART_COMMITS}}": bar_chart(commits, days, TEAL, "commits"),
        "{{CHART_FLEET24}}": hbar_chart(
            [("Beacon", last24(LOG_DIRS["Beacon"])),
             ("Highbeam", last24(LOG_DIRS["Highbeam"])),
             ("Lantern", last24(LOG_DIRS["Lantern"]))],
            AMBER, "wakings",
        ),
        "{{TOT_BEACON}}": str(win_total(beacon)),
        "{{TOT_HIGHBEAM}}": str(win_total(highbeam)),
        "{{TOT_LANTERN}}": str(win_total(lantern)),
        "{{TOT_COMMITS}}": str(win_total(commits)),
        "{{TABLE_BEACON}}": data_table(beacon, days, "wakings"),
        "{{TABLE_HIGHBEAM}}": data_table(highbeam, days, "wakings"),
        "{{TABLE_LANTERN}}": data_table(lantern, days, "wakings"),
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
