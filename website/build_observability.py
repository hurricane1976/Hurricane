#!/usr/bin/env python3
"""Regenerates website/observability.html -- the fleet's live agentic-observability
dashboard. Every panel is measured at generation time; there are no illustrative
numbers on this page.

Sources, all already on the box:

* **Per-run cost / tokens / turns / duration** -- the JSON result envelope
  `claude -p --output-format json` writes to `logs/<ts>.json` each waking
  (wired into wake.sh). Beacon and Highbeam (Claude Code) emit it; Lantern
  (Gemini CLI) and Lightning (opencode) run other runtimes that don't, so they
  carry a lane but no cost row -- never a fabricated number.
* **The rolled-up series** lives in `website/data/observability.jsonl`
  (committed, counters only -- never `.result` transcript text) so it outlives
  the 30-day pruning of `logs/`.
* **The run explorer** merges Beacon's git commits with the shared fleet
  timeline `shared/LOG.md`.

Charts are inline SVG in the site palette (amber #ff8a3d = Beacon, teal
#4fd1c5 = Highbeam / API compute; violet / slate for token + overhead spans).
Each bar carries a native <title> and a `data-tip` for chart-tooltip.js, and
every chart has a <details> data table beneath it.

`/api/observability` serves the same roll-up as JSON. Run standalone or via
deploy.sh.
"""
import json
import math
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "observability.template.html"
OUT = HERE / "observability.html"
STORE = HERE / "data" / "observability.jsonl"
SHARED_LOG = Path("/home/agent/shared/LOG.md")

# Per-waking JSON envelope directories, one per on-box agent. Only the Claude
# Code agents (Beacon, Highbeam) currently write *.json; the others are listed
# so the moment their wake.sh starts teeing one, it is picked up with no code
# change here.
JSON_LOG_DIRS = {
    "Beacon": ROOT / "logs",
    "Highbeam": Path("/home/agent/partner/logs"),
    "Lantern": Path("/home/agent/gemini-agent/logs"),
    "Lightning": Path("/home/agent/lightning/logs"),
}

TS_RE = re.compile(r"^(\d{8}T\d{6}Z)\.json$")
STORE_CAP = 4000  # rows kept on disk; ~2 years of an 8-agent fleet at 6x/day

# Independent hosts that publish their own observability roll-up, the same way
# they publish /fleet.json. Non-sensitive counters only; each host gates itself
# on a minimum sample count. Tidal's dashboard is HTML-only so far (no JSON).
SIBLING_OBS_URLS = {
    "Mountain": "https://mountainwake.org/observability.json",
    "Tidal": "https://tidalwake.org/observability.json",
}

import fleet_palette

# Channel hues (NOT agent identity): token-kind and wall-clock-span encodings
# in token_chart / duration_chart. Kept local; a small fixed categorical set.
AMBER = "#ff8a3d"
TEAL = "#4fd1c5"
BLUE = "#8ea0c8"
VIOLET = "#9b8cff"
SLATE = "#5b6472"
# Agent identity -> the canonical fleet palette (fleet_palette.py). Colour is
# the model family; the agent name always sits next to the mark.
AGENT_COLOR = {a: fleet_palette.agent_color(a)
               for a in ("Beacon", "Highbeam", "Lantern", "Lightning")}
CHART_W = 720

# --- fleet-wide per-run feed (the "Cost, tokens & wall-clock -- interactive"
# panel) -----------------------------------------------------------------------
# Beacon has first-party per-run rows only for its four on-box agents (the
# committed STORE). Tidal publishes a fleet-wide per-run JSONL -- every agent on
# every host, one row per waking -- the same artefact Mountain's matching panel
# reads. We take the eight off-box agents from it and keep our own four local.
# Cached on disk so a burst of manual rebuilds doesn't hammer tidalwake.org
# (same courtesy as fetch_sibling_obs, which is uncached but hit far less).
FLEET_RUN_FEED_URL = "https://tidalwake.org/data/observability.jsonl"
FLEET_RUN_FEED_CACHE = HERE / "data" / ".cache" / "fleet-run-feed.jsonl"
FLEET_RUN_FEED_TTL = 300  # seconds

# Fleet render order + per-agent hue: the canonical fleet palette. Colour
# encodes model family (amber=Claude, teal=Gemini, blue=DeepSeek,
# magenta=GLM); the panel shows one agent at a time with its name on the
# active tab, so identity is never colour-alone. Replaces the ad-hoc 12-hue
# set that failed CVD (Ridge<->Canyon deltaE 4.5).
MM_FLEET_ORDER = list(fleet_palette.FLEET_ORDER)
MM_LOCAL_AGENTS = {"Beacon", "Highbeam", "Lantern", "Lightning"}
MM_COLOR = dict(fleet_palette.AGENT)
MM_KEEP = 14  # runs shown per agent -- matches Mountain's / Tidal's panel


def _iso_from_ts(ts: str) -> str:
    """20260907T040233Z -> 2026-09-07T04:02:33Z"""
    return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[9:11]}:{ts[11:13]}:{ts[13:15]}Z"


MAX_SANE_MS = 2 * 60 * 60 * 1000  # a waking longer than 2h is a runaway, not data


def _sane_ms(v):
    """Drop implausible duration values (e.g. a sibling teeing `date +%s%3N`
    instead of an elapsed delta) so one bad envelope can't blow out a chart axis."""
    return v if isinstance(v, (int, float)) and 0 < v <= MAX_SANE_MS else None


def scan_json_logs() -> list[dict]:
    """One metrics row per parseable logs/<ts>.json across every agent dir."""
    rows = []
    for agent, d in JSON_LOG_DIRS.items():
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for f in entries:
            m = TS_RE.match(f.name)
            if not m:
                continue
            try:
                if f.stat().st_size == 0:
                    continue
                env = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(env, dict) or env.get("type") != "result":
                continue
            u = env.get("usage") or {}
            rows.append({
                "agent": agent,
                "ts": _iso_from_ts(m.group(1)),
                "cost_usd": env.get("total_cost_usd"),
                "turns": env.get("num_turns"),
                "duration_ms": _sane_ms(env.get("duration_ms")),
                "duration_api_ms": _sane_ms(env.get("duration_api_ms")),
                "input_tokens": u.get("input_tokens"),
                "output_tokens": u.get("output_tokens"),
                "cache_read_tokens": u.get("cache_read_input_tokens"),
                "cache_creation_tokens": u.get("cache_creation_input_tokens"),
                "is_error": bool(env.get("is_error")),
                "subtype": env.get("subtype"),
                "terminal_reason": env.get("terminal_reason"),
                "model": _canonical_model(env),
            })
    return rows


def _canonical_model(env: dict) -> str | None:
    """The model that did the run's real work.

    Not "most uncached input tokens" -- a Claude Code session serves the main
    thread's context from the prompt cache, so the main model's *uncached*
    `inputTokens` is tiny (~50) while a Haiku side-model (title/summary calls)
    shows ~1.2k uncached. Rank by spend instead (falling back to total billed
    tokens incl. cache), which tracks the main model unambiguously.
    """
    mu = env.get("modelUsage") or {}
    best, best_key = None, (-1.0, -1)
    for _, v in mu.items():
        toks = ((v.get("inputTokens") or 0) + (v.get("outputTokens") or 0)
                + (v.get("cacheReadInputTokens") or 0)
                + (v.get("cacheCreationInputTokens") or 0))
        key = (v.get("costUSD") or 0.0, toks)
        if key > best_key:
            best, best_key = v.get("canonicalModel"), key
    return best


def load_store() -> dict:
    rows = {}
    if STORE.exists():
        for line in STORE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rows[f"{r.get('agent')}:{r.get('ts')}"] = r
    return rows


def save_store(rows: dict) -> list[dict]:
    ordered = sorted(rows.values(), key=lambda r: (r.get("ts") or "", r.get("agent") or ""))
    ordered = ordered[-STORE_CAP:]
    STORE.parent.mkdir(exist_ok=True)
    STORE.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ordered))
    return ordered


# --- run explorer: runs as rows -----------------------------------------------

def _sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=8).stdout
    except Exception:
        return ""


def git_run_rows(limit: int = 30) -> list[dict]:
    out = _sh(["git", "-C", str(ROOT), "log", "-n", str(limit),
              "--date=format-local:%Y-%m-%d %H:%M", "--pretty=%cd\t%s"])
    rows = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        when, subj = line.split("\t", 1)
        rows.append({
            "agent": "Beacon",
            "when": when,
            "trigger": _trigger_of(subj),
            "outcome": _outcome_of(subj),
            "result": subj[:90],
        })
    return rows


LOG_LINE_RE = re.compile(
    r"^-\s*(\d{4}-\d{2}-\d{2})\s*[-—]+\s*(?:\[(\w+)\]\s*)?(.*)$"
)


def shared_log_rows(limit: int = 40) -> list[dict]:
    if not SHARED_LOG.exists():
        return []
    rows = []
    for line in SHARED_LOG.read_text().splitlines():
        m = LOG_LINE_RE.match(line.strip())
        if not m:
            continue
        date, agent, rest = m.group(1), m.group(2), m.group(3)
        if not agent:
            mm = re.match(r"^w?\d+\s*[:—-]*\s*(.*)", rest)
            agent = "Beacon"
            rest = mm.group(1) if mm else rest
        rows.append({
            "agent": agent,
            "when": date,
            "trigger": _trigger_of(rest),
            "outcome": _outcome_of(rest),
            "result": rest[:90],
        })
    return rows[-limit:]


def _trigger_of(s: str) -> str:
    low = s.lower()
    if "telegram" in low or "josh" in low:
        return "Telegram steer"
    if "highbeam" in low and ("finding" in low or "f1" in low or "review" in low):
        return "Highbeam finding"
    if "peer" in low or "mountain" in low or "tidal" in low:
        return "peer channel"
    return "scheduled"


def _outcome_of(s: str) -> str:
    low = s.lower()
    if "exit 1" in low or "exited with code" in low or " error" in low or "failed" in low:
        return "error"
    if any(w in low for w in ("quiet", "no-op", "no commit", "notes only", "nothing to")):
        return "noop"
    if any(w in low for w in ("ship", "deploy", "commit", "built", "wired", "fix", "add", "publish")):
        return "shipped"
    return "clean"


def run_explorer(limit: int = 18) -> list[dict]:
    merged = git_run_rows() + shared_log_rows()
    seen, uniq = set(), []
    for r in sorted(merged, key=lambda r: r["when"], reverse=True):
        key = (r["agent"], r["when"][:10], r["result"][:40].lower())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq[:limit]


# --- formatting -------------------------------------------------------------

def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def fmt_cost(v) -> str:
    return f"${v:,.4f}" if isinstance(v, (int, float)) else "—"


def fmt_cost2(v) -> str:
    return f"${v:,.2f}" if isinstance(v, (int, float)) else "—"


def fmt_int(v) -> str:
    return f"{v:,}" if isinstance(v, (int, float)) else "—"


def fmt_dur(ms) -> str:
    if not isinstance(ms, (int, float)):
        return "—"
    s = ms / 1000
    return f"{s:.0f}s" if s < 90 else f"{s / 60:.1f}m"


def kfmt(v) -> str:
    v = float(v or 0)
    if v >= 1e6:
        return f"{v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{v / 1e3:.0f}k"
    return f"{v:.0f}"


def nice_top(v: float) -> float:
    if v <= 0:
        return 1.0
    exp = math.floor(math.log10(v))
    base = 10 ** exp
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * base:
            return m * base
    return 10 * base


def _tok_total(r: dict) -> int:
    return ((r.get("cache_read_tokens") or 0) + (r.get("cache_creation_tokens") or 0)
            + (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0))


def _label(r: dict) -> str:
    return r["ts"][5:16].replace("T", " ")


# --- charts (inline SVG, site palette) ------------------------------------

def _grid_y(ml, mr, mt, ph, axis_top, fmt):
    grid, ylab = [], []
    for t in range(5):
        gv = axis_top * t / 4
        gy = mt + ph - gv / axis_top * ph
        grid.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{CHART_W - mr}" y2="{gy:.1f}" '
                    f'stroke="var(--line)" stroke-width="1"/>')
        ylab.append(f'<text x="{ml - 6}" y="{gy + 3:.1f}" text-anchor="end" class="ax">{fmt(gv)}</text>')
    return "".join(grid), "".join(ylab)


def _x_labels(rs, ml, slot, y):
    n = len(rs)
    show = sorted({0, n - 1, n // 4, n // 2, 3 * n // 4})
    return "".join(
        f'<text x="{ml + i * slot + slot / 2:.1f}" y="{y}" text-anchor="middle" '
        f'class="ax">{esc(_label(rs[i]))}</text>' for i in show
    )


def cost_chart(runs: list[dict], keep: int = 28) -> str:
    rs = runs[-keep:]
    if not rs:
        return ""
    H = 214
    ml, mr, mt, mb = 44, 12, 12, 30
    pw, ph = CHART_W - ml - mr, H - mt - mb
    axis_top = nice_top(max(r["cost_usd"] for r in rs))
    n = len(rs)
    slot = pw / n
    bw = min(slot * 0.66, 24)
    grid, ylab = _grid_y(ml, mr, mt, ph, axis_top, lambda v: f"${v:.2f}")
    bars = []
    for i, r in enumerate(rs):
        h = r["cost_usd"] / axis_top * ph
        x = ml + i * slot + (slot - bw) / 2
        y = mt + ph - h
        col = AGENT_COLOR.get(r["agent"], AMBER)
        tip = (f'{r["agent"]} · {_label(r)} · {fmt_cost(r["cost_usd"])} · '
               f'{fmt_int(r.get("turns"))} turns · {fmt_dur(r.get("duration_ms"))} wall')
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="3" '
                    f'fill="{col}" data-tip="{esc(tip)}"><title>{esc(tip)}</title></rect>')
    return (f'<svg viewBox="0 0 {CHART_W} {H}" class="chart chart-in" role="img" '
            f'aria-label="US-dollar cost per instrumented run, {n} most recent runs">'
            f'{grid}{ylab}{"".join(bars)}{_x_labels(rs, ml, slot, H - 8)}</svg>')


def token_chart(runs: list[dict], keep: int = 28) -> str:
    rs = runs[-keep:]
    if not rs:
        return ""
    H = 214
    ml, mr, mt, mb = 46, 12, 12, 30
    pw, ph = CHART_W - ml - mr, H - mt - mb
    axis_top = nice_top(max(_tok_total(r) for r in rs) or 1)
    n = len(rs)
    slot = pw / n
    bw = min(slot * 0.66, 24)
    grid, ylab = _grid_y(ml, mr, mt, ph, axis_top, kfmt)
    segs = [("cache_read_tokens", "cache read", TEAL),
            ("cache_creation_tokens", "cache write", VIOLET),
            ("input_tokens", "input", BLUE),
            ("output_tokens", "output", AMBER)]
    bars = []
    for i, r in enumerate(rs):
        x = ml + i * slot + (slot - bw) / 2
        acc = 0.0
        for key, lbl, col in segs:
            val = r.get(key) or 0
            if val <= 0:
                continue
            h = val / axis_top * ph
            y = mt + ph - acc - h
            acc += h
            tip = f'{r["agent"]} · {_label(r)} · {lbl}: {val:,}'
            bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" '
                        f'fill="{col}" data-tip="{esc(tip)}"><title>{esc(tip)}</title></rect>')
    return (f'<svg viewBox="0 0 {CHART_W} {H}" class="chart chart-in" role="img" '
            f'aria-label="Billed tokens per instrumented run by kind, {n} most recent runs">'
            f'{grid}{ylab}{"".join(bars)}{_x_labels(rs, ml, slot, H - 8)}</svg>')


DUR_WINDOW = 16  # runs shown in the duration chart + covered by its note


def duration_chart(runs: list[dict], keep: int = DUR_WINDOW) -> str:
    rs = runs[-keep:][::-1]
    if not rs:
        return ""
    rowh = 21
    ml, mr, mt, mb = 128, 16, 10, 26
    ph = rowh * len(rs)
    H = mt + ph + mb
    pw = CHART_W - ml - mr
    axis_top_ms = nice_top(max((r.get("duration_ms") or 0) for r in rs) or 1000)
    vlines, xlab = [], []
    for t in range(5):
        gv = axis_top_ms * t / 4
        gx = ml + gv / axis_top_ms * pw
        vlines.append(f'<line x1="{gx:.1f}" y1="{mt}" x2="{gx:.1f}" y2="{mt + ph}" '
                      f'stroke="var(--line)" stroke-width="1"/>')
        xlab.append(f'<text x="{gx:.1f}" y="{H - 8}" text-anchor="middle" class="ax">'
                    f'{gv / 1000:.0f}s</text>')
    rows = []
    for i, r in enumerate(rs):
        y = mt + i * rowh + 3
        wall = r.get("duration_ms") or 0
        api = min(r.get("duration_api_ms") or 0, wall)
        over = max(wall - api, 0)
        aw = api / axis_top_ms * pw
        ow = over / axis_top_ms * pw
        rows.append(f'<text x="{ml - 8}" y="{y + 11:.1f}" text-anchor="end" class="ax">'
                    f'{esc(r["agent"][:2])} {esc(_label(r))}</text>')
        t1 = f'{r["agent"]} · {_label(r)} · API compute {fmt_dur(api)}'
        t2 = f'{r["agent"]} · {_label(r)} · orchestration {fmt_dur(over)}'
        rows.append(f'<rect x="{ml}" y="{y}" width="{aw:.1f}" height="15" rx="2" fill="{TEAL}" '
                    f'data-tip="{esc(t1)}"><title>{esc(t1)}</title></rect>')
        rows.append(f'<rect x="{ml + aw:.1f}" y="{y}" width="{ow:.1f}" height="15" rx="2" fill="{SLATE}" '
                    f'data-tip="{esc(t2)}"><title>{esc(t2)}</title></rect>')
    return (f'<svg viewBox="0 0 {CHART_W} {H}" class="chart chart-in" role="img" '
            f'aria-label="Wall-clock split into API compute and orchestration overhead, '
            f'{len(rs)} most recent runs">'
            f'{"".join(vlines)}{"".join(rows)}{"".join(xlab)}</svg>')


# --- run-activity heatmap (agent x hour-of-day) --------------------------

# Single-hue amber sequential ramp, validated for a dark chart surface
# (dataviz scripts/validate_palette.js --mode dark --surface #10151d --ordinal:
# monotone lightness, adjacent dL >= 0.06, light end 2.5:1 on the card, one hue).
HEAT_RAMP = ["#7a4a2a", "#a35c30", "#c8763a", "#e89444", "#ffb85c"]
HEAT_EMPTY = "rgba(255,255,255,0.03)"
HEAT_ERR = "#e08a6a"
HEAT_ORDER = ["Beacon", "Highbeam", "Lantern", "Lightning"]


def _heat_agents(rows: list[dict]) -> list[str]:
    present = {r["agent"] for r in rows}
    ordered = [a for a in HEAT_ORDER if a in present]
    return ordered + sorted(present - set(ordered))


def heatmap_chart(rows: list[dict]) -> tuple[str, str]:
    """(inline-SVG heatmap, data-table body) of runs by agent x clock hour (UTC).

    One cell per (agent, hour); fill = sequential amber scaled to the busiest
    cell; a cell that contains an errored run gets an amber-red ring. Every
    on-box agent that writes a result envelope is a row -- off-box hosts publish
    only aggregate roll-ups (no per-run timestamps) so they cannot appear here.
    """
    agents = _heat_agents(rows)
    if not rows or not agents:
        return "", ""
    # grid[agent][hour] = [count, errored_count, latest_date]
    grid = {a: {h: [0, 0, ""] for h in range(24)} for a in agents}
    for r in rows:
        a = r["agent"]
        if a not in grid:
            continue
        try:
            h = int(r["ts"][11:13])
        except (ValueError, IndexError):
            continue
        cell = grid[a][h]
        cell[0] += 1
        if r.get("is_error"):
            cell[1] += 1
        d = r["ts"][:10]
        if d > cell[2]:
            cell[2] = d
    peak = max((grid[a][h][0] for a in agents for h in range(24)), default=0) or 1

    ml, mr, mt, mb = 96, 12, 22, 24
    cw = (CHART_W - ml - mr) / 24
    ch = 26
    gap = 2
    H = mt + ch * len(agents) + mb

    marks, xlab, ylab = [], [], []
    for h in range(0, 24, 3):
        gx = ml + h * cw + cw / 2
        xlab.append(f'<text x="{gx:.1f}" y="{mt - 8:.1f}" text-anchor="middle" '
                    f'class="ax">{h:02d}</text>')
    for ai, a in enumerate(agents):
        cy = mt + ai * ch
        ylab.append(f'<text x="{ml - 10}" y="{cy + ch / 2 + 3:.1f}" text-anchor="end" '
                    f'class="ax">{esc(a)}</text>')
        for h in range(24):
            cnt, errs, last = grid[a][h]
            x = ml + h * cw
            if cnt == 0:
                marks.append(f'<rect class="cell" x="{x + gap / 2:.1f}" y="{cy + gap / 2:.1f}" '
                             f'width="{cw - gap:.1f}" height="{ch - gap:.1f}" rx="2" '
                             f'fill="{HEAT_EMPTY}"/>')
                continue
            bucket = min(5, math.ceil(cnt / peak * 5)) or 1
            fill = HEAT_RAMP[bucket - 1]
            ring = (f' stroke="{HEAT_ERR}" stroke-width="2"' if errs else "")
            tip = (f'{a} · {h:02d}:00–{(h + 1) % 24:02d}:00 UTC · '
                   f'{cnt} run{"s" if cnt != 1 else ""}'
                   + (f' ({errs} errored)' if errs else "")
                   + (f' · latest {last}' if last else ""))
            marks.append(
                f'<rect class="cell" x="{x + gap / 2:.1f}" y="{cy + gap / 2:.1f}" '
                f'width="{cw - gap:.1f}" height="{ch - gap:.1f}" rx="2" fill="{fill}"{ring} '
                f'data-tip="{esc(tip)}"><title>{esc(tip)}</title></rect>')
            tcol = "#0a0d13" if bucket >= 3 else "#e8eaed"
            marks.append(
                f'<text x="{x + cw / 2:.1f}" y="{cy + ch / 2 + 3:.1f}" text-anchor="middle" '
                f'style="font-family:\'IBM Plex Mono\',monospace;font-size:10px;fill:{tcol};'
                f'pointer-events:none;">{cnt}</text>')

    svg = (f'<svg viewBox="0 0 {CHART_W} {H}" class="heat" role="img" '
           f'aria-label="Run count by agent and clock hour (UTC); busiest cell is '
           f'{peak} runs">{"".join(xlab)}{"".join(ylab)}{"".join(marks)}</svg>')

    # data table: agent x 3-hour block totals, so it fits without a 24-col scroll
    blocks = [(b, b + 3) for b in range(0, 24, 3)]
    head = "".join(f"<th>{s:02d}–{e:02d}</th>" for s, e in blocks)
    trs = []
    for a in agents:
        tds = []
        row_total = 0
        for s, e in blocks:
            v = sum(grid[a][h][0] for h in range(s, e))
            row_total += v
            tds.append(f'<td class="mono">{v or "&middot;"}</td>')
        trs.append(f'<tr><td>{esc(a)}</td>' + "".join(tds)
                   + f'<td class="mono">{row_total}</td></tr>')
    table = (f'<thead><tr><th>Agent</th>{head}<th>Total</th></tr></thead>'
             f'<tbody>{"".join(trs)}</tbody>')
    return svg, table


# --- failure-reason breakdown ------------------------------------------------

# Categorical (not sequential) -- each bucket is an independent identity, so the
# palette is a qualitative scale, not shades of one hue. Swatches are tested on
# the card surface (#10151d) for AA contrast and colour-blind separation per
# Lantern's w102 design spec
# (shared/outbox/agentic-monitoring-research-w311/LANTERN-DESIGN.md, sec 1).
FAIL_BUCKETS = [
    ("api-fault",  "Provider API fault",   "#e5c07b"),  # warm amber
    ("exec-error", "Execution error",      "#e06c75"),  # soft coral
    ("max-turns",  "Turn ceiling hit",     "#c678dd"),  # violet
    ("other",      "Other / unclassified", "#8b93a1"),  # muted slate
]
FAIL_LABEL = {k: (lbl, col) for k, lbl, col in FAIL_BUCKETS}


def _fail_reason(r: dict) -> str | None:
    """Bucket an errored run by the result envelope's own fields. Returns None
    for a clean run. `api-fault` needs a positive signal
    (`terminal_reason == "api_error"`); an is_error envelope with nothing
    classifiable lands in `other` rather than being assumed a provider fault
    (an early exec crash that only managed a minimal envelope looks the same as
    a provider non-start, so don't guess)."""
    if not r.get("is_error"):
        return None
    sub = (r.get("subtype") or "").lower()
    term = (r.get("terminal_reason") or "").lower()
    if term == "api_error":
        return "api-fault"
    if "max_turns" in sub or term == "error_max_turns":
        return "max-turns"
    if sub.startswith("error") or term.startswith("error"):
        return "exec-error"
    return "other"


def _fail_counts(err_rows: list[dict]) -> dict:
    counts = {}
    for r in err_rows:
        k = _fail_reason(r)
        counts[k] = counts.get(k, 0) + 1
    return counts


def failure_bar(counts: dict) -> str:
    """One horizontal stacked bar; segment width proportional to count, clamped
    so a rare bucket stays visible. No load animation (categorical, not a trend)."""
    total = sum(counts.values())
    if not total:
        return ""
    W, H, bar_h = CHART_W, 46, 30
    pad = 2
    present = [(k, counts[k]) for k, _, _ in FAIL_BUCKETS if counts.get(k)]
    avail = W - pad * max(len(present) - 1, 0)
    segs, x = [], 0.0
    for k, c in present:
        w = max(7.0, c / total * avail)
        lbl, col = FAIL_LABEL[k]
        pct = c / total * 100
        tip = f'{lbl}: {c} of {total} errored run{"s" if total != 1 else ""} ({pct:.0f}%)'
        segs.append(
            f'<rect x="{x:.1f}" y="{(H - bar_h) / 2:.1f}" width="{w:.1f}" height="{bar_h}" '
            f'rx="4" fill="{col}" data-tip="{esc(tip)}"><title>{esc(tip)}</title></rect>')
        if w > 22:
            segs.append(
                f'<text x="{x + w / 2:.1f}" y="{H / 2 + 4:.1f}" text-anchor="middle" '
                f'style="font-family:\'IBM Plex Mono\',monospace;font-size:12px;'
                f'font-weight:600;fill:#0a0d13;pointer-events:none;">{c}</text>')
        x += w + pad
    return (f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
            f'aria-label="Failure-reason breakdown of {total} errored runs; '
            f'{", ".join(f"{FAIL_LABEL[k][0]} {c}" for k, c in present)}">'
            f'{"".join(segs)}</svg>')


def failure_legend(counts: dict) -> str:
    return "".join(
        f'<span><i style="background:{col}"></i>{esc(lbl)}: {counts.get(k, 0)}</span>'
        for k, lbl, col in FAIL_BUCKETS)


def failure_table(err_rows: list[dict]) -> str:
    if not err_rows:
        return ('<tr><td colspan="5" style="text-align:center;color:var(--muted);">'
                'no errored runs in the committed series</td></tr>')
    counts, latest, example = {}, {}, {}
    for r in err_rows:
        k = _fail_reason(r)
        counts[k] = counts.get(k, 0) + 1
        ts = r.get("ts") or ""
        if ts >= latest.get(k, ""):
            latest[k], example[k] = ts, r.get("agent") or "?"
    total = sum(counts.values())
    trs = []
    for k, lbl, _ in FAIL_BUCKETS:
        c = counts.get(k, 0)
        if not c:
            continue
        trs.append(
            f'<tr><td>{esc(lbl)}</td><td class="mono">{c}</td>'
            f'<td class="mono">{c / total * 100:.0f}%</td>'
            f'<td class="mono">{esc(latest.get(k, "")[:16].replace("T", " "))}</td>'
            f'<td class="mono">{esc(example.get(k, ""))}</td></tr>')
    return "".join(trs)


# --- tables --------------------------------------------------------------

def agent_summary(instrumented: list[dict]) -> str:
    if not instrumented:
        return ('<tr><td colspan="8" style="text-align:center;color:var(--muted);">'
                'no instrumented runs yet</td></tr>')
    out = []
    for a in sorted({r["agent"] for r in instrumented}):
        rs = [r for r in instrumented if r["agent"] == a]
        k = len(rs)
        tc = sum(r["cost_usd"] for r in rs)
        mt_ = sum((r.get("duration_ms") or 0) for r in rs) / k
        tt = sum((r.get("turns") or 0) for r in rs) / k
        tok = sum(_tok_total(r) for r in rs) / k
        err = sum(1 for r in rs if r.get("is_error"))
        out.append(
            f'<tr><td>{esc(a)}</td><td class="mono">{k}</td>'
            f'<td class="mono">{fmt_cost2(tc)}</td>'
            f'<td class="mono">{fmt_cost(tc / k)}</td>'
            f'<td class="mono">{tt:.0f}</td>'
            f'<td class="mono">{fmt_dur(mt_)}</td>'
            f'<td class="mono">{kfmt(tok)}</td>'
            f'<td class="mono">{err}</td></tr>')
    return "\n".join(out)


def all_agent_summary(rows: list[dict]) -> str:
    """Every agent that emits a result envelope, cost-bearing or not.

    The cost panels above filter to runs that carry a dollar figure. Only the
    Gemini runtime (Lantern) reports tokens and timing but no billed cost, so
    this table is the only place it surfaces and its mean $ reads `n/a`.
    Lightning (DeepSeek via OpenRouter) does carry a real cost and appears in
    the cost panels too.
    """
    agents = sorted({r["agent"] for r in rows})
    if not agents:
        return ('<tr><td colspan="8" style="text-align:center;color:var(--muted);">'
                'no result envelopes yet</td></tr>')
    out = []
    for a in agents:
        rs = [r for r in rows if r["agent"] == a]
        k = len(rs)
        model = next((r.get("model") for r in reversed(rs) if r.get("model")), None)
        costs = [r["cost_usd"] for r in rs if isinstance(r.get("cost_usd"), (int, float))]
        mc = fmt_cost(sum(costs) / len(costs)) if costs else \
            '<span style="color:var(--muted);">n/a</span>'
        durs = [r["duration_ms"] for r in rs if isinstance(r.get("duration_ms"), (int, float))]
        mw = fmt_dur(sum(durs) / len(durs)) if durs else "&mdash;"
        tt = sum((r.get("turns") or 0) for r in rs) / k
        tok = sum(_tok_total(r) for r in rs) / k
        err = sum(1 for r in rs if r.get("is_error"))
        out.append(
            f'<tr><td>{esc(a)}</td><td class="mono">{esc(model) if model else "&mdash;"}</td>'
            f'<td class="mono">{k}</td>'
            f'<td class="mono">{tt:.0f}</td>'
            f'<td class="mono">{mw}</td>'
            f'<td class="mono">{kfmt(tok)}</td>'
            f'<td class="mono">{mc}</td>'
            f'<td class="mono">{err}</td></tr>')
    return "\n".join(out)


# --- spend by model family ------------------------------------------------

# Substring -> family label. First match wins; a non-empty model string that
# matches nothing lands in "Other" (honest -- an unknown provider, not a guess).
# A null model (provider non-start envelope) is not attributable and is excluded.
MODEL_FAMILIES = [
    ("claude", "Claude"),
    ("gemini", "Gemini"),
    ("deepseek", "DeepSeek"),
    ("glm", "GLM"),
]


def _family_of(model) -> str | None:
    if not model:
        return None
    m = str(model).lower()
    for key, label in MODEL_FAMILIES:
        if key in m:
            return label
    return "Other"


def _fam_spend(rs: list[dict]) -> float:
    return sum(r["cost_usd"] for r in rs if isinstance(r.get("cost_usd"), (int, float)))


def model_family_table(rows: list[dict]) -> str:
    """The committed series rolled up by model-provider family. Cost columns
    read n/a for a family with no billed run (Gemini); token / turn means are
    populated for every runtime that writes an envelope."""
    fam_rows: dict[str, list[dict]] = {}
    for r in rows:
        fam = _family_of(r.get("model"))
        if fam:
            fam_rows.setdefault(fam, []).append(r)
    if not fam_rows:
        return ('<tr><td colspan="8" style="text-align:center;color:var(--muted);">'
                'no runs carry a model id yet</td></tr>')
    muted = '<span style="color:var(--muted);">n/a</span>'
    out = []
    for fam in sorted(fam_rows, key=lambda f: (-_fam_spend(fam_rows[f]), -len(fam_rows[f]), f)):
        rs = fam_rows[fam]
        k = len(rs)
        agents = ", ".join(sorted({r["agent"] for r in rs}))
        costs = [r["cost_usd"] for r in rs if isinstance(r.get("cost_usd"), (int, float))]
        tc = fmt_cost2(sum(costs)) if costs else muted
        # Mean $/run divides by every run in the family (k), not just the billed
        # ones, so this column stays "Total $ / Runs" -- consistent with the two
        # neighbouring means. A family with no billed run at all reads n/a.
        mc = fmt_cost(sum(costs) / k) if costs else muted
        tok = sum(_tok_total(r) for r in rs) / k
        tt = sum((r.get("turns") or 0) for r in rs) / k
        err = sum(1 for r in rs if r.get("is_error"))
        out.append(
            f'<tr><td>{esc(fam)}</td><td>{esc(agents)}</td>'
            f'<td class="mono">{k}</td><td class="mono">{tc}</td>'
            f'<td class="mono">{mc}</td><td class="mono">{kfmt(tok)}</td>'
            f'<td class="mono">{tt:.0f}</td><td class="mono">{err}</td></tr>')
    return "\n".join(out)


def _fmt_s(v) -> str:
    if not isinstance(v, (int, float)) or v <= 0:
        return "&mdash;"
    return f"{v:.0f}s" if v < 90 else f"{v / 60:.1f}m"


def fetch_sibling_obs() -> list[tuple[str, dict]]:
    """GET each host's observability.json. Returns [(host_label, doc), ...] for
    every one that answers with a JSON object; silently skips the unreachable."""
    out = []
    for host, url in SIBLING_OBS_URLS.items():
        try:
            raw = subprocess.run(["curl", "-s", "--max-time", "8", url],
                                 capture_output=True, text=True, timeout=12).stdout
            doc = json.loads(raw)
        except Exception:
            continue
        if isinstance(doc, dict):
            out.append((host, doc))
    return out


def _offbox_tr(agent: str, host: str, runs, total_c, mean_c, mean_dur, mean_tok, ok_pct, seen) -> str:
    ok = f"{ok_pct:.0f}%" if isinstance(ok_pct, (int, float)) else "&mdash;"
    return (f'<tr><td>{esc(agent)}</td><td class="mono">{esc(host)}</td>'
            f'<td class="mono">{fmt_int(runs)}</td>'
            f'<td class="mono">{fmt_cost2(total_c) if isinstance(total_c, (int, float)) else "n/a"}</td>'
            f'<td class="mono">{fmt_cost(mean_c) if isinstance(mean_c, (int, float)) else "n/a"}</td>'
            f'<td class="mono">{_fmt_s(mean_dur)}</td>'
            f'<td class="mono">{kfmt(mean_tok) if isinstance(mean_tok, (int, float)) else "&mdash;"}</td>'
            f'<td class="mono">{ok}</td>'
            f'<td class="mono">{esc(seen)[:16] if seen else "&mdash;"}</td></tr>')


def offbox_obs(fetched: list[tuple[str, dict]]) -> tuple[str, str]:
    """(table-body rows, prose note) for the off-box observability section.
    The publishing agent's own numbers come from the top-level fields; its
    co-located siblings come from the `siblings` map, each shown only once it
    has crossed its own sample gate -- same honesty rule as our own page."""
    rows, waiting, empty_sibs = [], [], []
    for host, doc in fetched:
        gate = doc.get("min_samples") or 5
        k = doc.get("samples") or 0
        tot_tok = doc.get("total_tokens")
        mean_tok = (tot_tok / k) if isinstance(tot_tok, (int, float)) and k else None
        if k >= gate:
            rows.append(_offbox_tr(
                host, f"{host.lower()}wake.org", k,
                doc.get("total_cost_usd"), doc.get("avg_cost_usd"),
                doc.get("avg_duration_s"),
                mean_tok, doc.get("success_rate_pct"),
                (doc.get("last_wake") or {}).get("ts") if isinstance(doc.get("last_wake"), dict)
                else doc.get("last_wake") or doc.get("generated_at"),
            ))
        else:
            waiting.append(f"{host} ({k}/{gate})")
        sib = doc.get("siblings")
        if isinstance(sib, dict) and not sib:
            empty_sibs.append(host)
        if isinstance(sib, dict):
            for name, s in sorted(sib.items()):
                if not isinstance(s, dict):
                    continue
                sk = s.get("samples") or 0
                sgate = s.get("min_samples") or gate
                nm = name.capitalize()
                if sk < sgate:
                    waiting.append(f"{nm} ({sk}/{sgate})")
                    continue
                avg_c = s.get("avg_cost_usd")
                avg_tok = s.get("avg_tokens")
                rows.append(_offbox_tr(
                    # siblings publish averages only, no reported cumulative total
                    nm, f"{host}’s host", sk,
                    None, avg_c,
                    s.get("avg_duration_s"),
                    avg_tok if isinstance(avg_tok, (int, float)) else None,
                    s.get("success_rate_pct"),
                    s.get("last_seen") or s.get("since"),
                ))

    if not fetched:
        note = ("No host roll-up was reachable at generation time &mdash; this "
                "section fills when the fetch next succeeds.")
    elif waiting:
        note = ("Still below the sample gate, so not yet shown: "
                + ", ".join(waiting) + ".")
    elif not empty_sibs:
        note = "Every published lane has crossed its sample gate."
    else:
        note = "Every host lane shown has crossed its sample gate."
    if empty_sibs:
        note += (" " + " and ".join(empty_sibs) + "&rsquo;s co-located siblings "
                 "publish an empty roll-up so far and appear here once each "
                 "crosses that host&rsquo;s sample gate.")
    note += (" Cost columns read &ldquo;n/a&rdquo; for non-billed runtimes "
             "(Gemini, GLM) that have no per-run price to report.")
    body = "\n".join(rows) or (
        '<tr><td colspan="9" style="text-align:center;color:var(--muted);">'
        'no host has crossed its sample gate yet</td></tr>')
    return body, note


# --- interactive multi-metric panel -----------------------------------------

def fetch_fleet_run_feed() -> list[dict]:
    """Tidal's fleet-wide per-run JSONL, disk-cached for FLEET_RUN_FEED_TTL.

    Returns [] and leaves any stale cache in place if the fetch fails and no
    cache exists -- callers degrade to "feed unreachable" per agent, never to a
    fabricated row."""
    cache = FLEET_RUN_FEED_CACHE
    fresh = False
    try:
        fresh = cache.exists() and (time.time() - cache.stat().st_mtime) < FLEET_RUN_FEED_TTL
    except OSError:
        fresh = False
    if not fresh:
        try:
            raw = subprocess.run(
                ["curl", "-sS", "--max-time", "12", FLEET_RUN_FEED_URL],
                capture_output=True, text=True, timeout=15).stdout
            probe = [json.loads(ln) for ln in raw.splitlines() if ln.strip()]
            if probe and all(isinstance(r, dict) and r.get("agent") for r in probe):
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(raw)
        except Exception:
            pass  # keep whatever cache we have
    if not cache.exists():
        return []
    rows = []
    for ln in cache.read_text().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("agent") and r.get("ts"):
            rows.append(r)
    return rows


MM_W, MM_H = CHART_W, 214
MM_METRICS = [("cost", "Cost / run"), ("tokens", "Tokens / run"),
              ("wall", "Wall-clock / run")]


def _mm_axis_fmt(metric: str, top: float):
    if metric == "cost":
        dp = 4 if top < 0.05 else 3 if top < 1 else 2
        return lambda v: f"${v:.{dp}f}"
    if metric == "tokens":
        return kfmt
    return (lambda v: f"{v / 60:.0f}m") if top >= 600 else (lambda v: f"{v:.0f}s")


def _mm_val_fmt(metric: str):
    if metric == "cost":
        return lambda v: "—" if v is None else (f"${v:.3f}" if v < 1 else f"${v:.2f}")
    if metric == "tokens":
        return lambda v: "—" if v is None else f"{kfmt(v)} tok"
    return lambda v: "—" if v is None else (f"{v:.0f}s" if v < 90 else f"{v / 60:.1f}m")


def _mm_svg(agent: str, lane: dict, metric: str) -> str:
    """One inline-SVG bar chart -- geometry identical to the client renderer in
    the panel's inline <script>, so the no-JS default and a JS re-render match."""
    vals = lane["series"][metric]
    axis, full, oks, color = lane["axis"], lane["full"], lane["ok"], lane["color"]
    ml = {"cost": 46, "tokens": 48, "wall": 44}[metric]
    mr, mt, mb = 12, 12, 30
    pw, ph = MM_W - ml - mr, MM_H - mt - mb
    nums = [v for v in vals if isinstance(v, (int, float))]
    top = nice_top(max(nums) if nums else 1)
    n = len(vals) or 1
    slot = pw / n
    bw = min(slot * 0.66, 24)
    afmt, vfmt = _mm_axis_fmt(metric, top), _mm_val_fmt(metric)
    parts = []
    for t in range(5):
        gv = top * t / 4
        gy = mt + ph - gv / top * ph
        parts.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{MM_W - mr}" y2="{gy:.1f}" '
                     f'stroke="var(--line)" stroke-width="1"/>')
        parts.append(f'<text x="{ml - 6}" y="{gy + 3:.1f}" text-anchor="end" '
                     f'class="ax">{esc(afmt(gv))}</text>')
    for i, v in enumerate(vals):
        if not isinstance(v, (int, float)):
            continue
        h = v / top * ph if top else 0
        x = ml + i * slot + (slot - bw) / 2
        y = mt + ph - h
        ok = oks[i] is not False
        col = color if ok else "#e08a6a"
        tip = f'{agent} · {full[i]} · {vfmt(v)}' + ("" if ok else " · error")
        parts.append(f'<rect data-i="{i}" x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                     f'height="{max(h, 0):.1f}" rx="3" fill="{col}" '
                     f'data-tip="{esc(tip)}"><title>{esc(tip)}</title></rect>')
    show = sorted({0, n - 1, n // 4, n // 2, 3 * n // 4})
    for i in show:
        if 0 <= i < len(axis):
            parts.append(f'<text x="{ml + i * slot + slot / 2:.1f}" y="{MM_H - 8}" '
                         f'text-anchor="middle" class="ax">{esc(axis[i])}</text>')
    label = next(lbl for k, lbl in MM_METRICS if k == metric)
    return (f'<svg viewBox="0 0 {MM_W} {MM_H}" class="mm-svg" role="img" '
            f'aria-label="{esc(label + " for " + agent + ", last " + str(len(vals)) + " runs")}">'
            f'{"".join(parts)}</svg>')


def _mm_lanes(store_rows: list[dict]) -> tuple[dict, list[str]]:
    """{agent: {color, axis[], full[], ok[], series{cost,tokens,wall}}} for every
    fleet member with >=1 run, plus the list of members with no reachable data."""
    feed = fetch_fleet_run_feed()
    remote: dict[str, list[dict]] = {}
    for r in feed:
        remote.setdefault(r["agent"], []).append(r)
    local: dict[str, list[dict]] = {}
    for r in store_rows:
        if r["agent"] in MM_LOCAL_AGENTS:
            local.setdefault(r["agent"], []).append(r)

    lanes, missing = {}, []
    for a in MM_FLEET_ORDER:
        src = local.get(a) if a in MM_LOCAL_AGENTS else remote.get(a)
        rs = sorted(src or [], key=lambda r: r.get("ts") or "")[-MM_KEEP:]
        if not rs:
            missing.append(a)
            continue
        axis, full, oks = [], [], []
        series = {"cost": [], "tokens": [], "wall": []}
        for r in rs:
            ts = r.get("ts") or ""
            axis.append(ts[11:16])
            full.append((ts[:10] + " " + ts[11:19] + " UTC").strip())
            oks.append(not r.get("is_error"))
            c = r.get("cost_usd")
            series["cost"].append(round(c, 6) if isinstance(c, (int, float)) else None)
            tok = _tok_total(r)
            series["tokens"].append(tok if tok > 0 else None)
            d = r.get("duration_ms")
            series["wall"].append(round(d / 1000) if isinstance(d, (int, float)) and d > 0 else None)
        lanes[a] = {"color": MM_COLOR.get(a, AMBER), "axis": axis, "full": full,
                    "ok": oks, "series": series}
    return lanes, missing


def _mm_table(agent: str, lane: dict, visible: bool) -> str:
    vc, vt, vw = _mm_val_fmt("cost"), _mm_val_fmt("tokens"), _mm_val_fmt("wall")
    trs = []
    for i in range(len(lane["full"])):
        s = lane["series"]
        oc = "" if lane["ok"][i] is not False else ' class="outcome error"'
        trs.append(
            f'<tr><td class="mono">{esc(lane["full"][i])}</td>'
            f'<td class="mono">{esc(vc(s["cost"][i]))}</td>'
            f'<td class="mono">{esc(vt(s["tokens"][i]))}</td>'
            f'<td class="mono"{oc}>{esc(vw(s["wall"][i]))}</td></tr>')
    hide = "" if visible else " hidden"
    return (f'<table class="data-table" data-mm-table="{esc(agent)}"{hide} '
            f'style="min-width:32rem;"><thead><tr><th>Wake (UTC)</th><th>Cost</th>'
            f'<th>Tokens</th><th>Wall</th></tr></thead><tbody>{"".join(trs)}'
            f'</tbody></table>')


def multimetric_block(store_rows: list[dict]) -> str:
    lanes, missing = _mm_lanes(store_rows)
    present = [a for a in MM_FLEET_ORDER if a in lanes]
    if not present:
        return ('<p style="color:var(--muted);">The fleet-wide per-run feed was '
                'unreachable at generation time and no cache exists yet &mdash; '
                'this panel fills on the next build that reaches '
                '<a href="https://tidalwake.org/data/observability.jsonl" '
                'rel="noopener">tidalwake.org/data/observability.jsonl</a>.</p>')

    default_agent = "Beacon" if "Beacon" in lanes else present[0]

    # agent tabs -- every fleet member gets one; unreachable ones render disabled
    atabs = []
    for a in MM_FLEET_ORDER:
        col = MM_COLOR.get(a, AMBER)
        if a in lanes:
            active = " is-active" if a == default_agent else ""
            press = "true" if a == default_agent else "false"
            atabs.append(
                f'<button type="button" class="mm-tab{active}" data-mm-agent="{esc(a)}" '
                f'aria-pressed="{press}"><span class="agent-dot" style="background:{col}">'
                f'</span>{esc(a)}</button>')
        else:
            atabs.append(
                f'<button type="button" class="mm-tab" data-mm-agent="{esc(a)}" disabled '
                f'title="no per-run feed reachable for {esc(a)}"><span class="agent-dot" '
                f'style="background:{col};opacity:0.4"></span>{esc(a)}</button>')
    mtabs = [
        f'<button type="button" class="mm-tab{" is-active" if k == "cost" else ""}" '
        f'data-mm-metric="{k}" aria-pressed="{"true" if k == "cost" else "false"}">{lbl}</button>'
        for k, lbl in MM_METRICS]

    tables = "".join(_mm_table(a, lanes[a], a == default_agent) for a in present)
    blob = json.dumps({"order": MM_FLEET_ORDER, "default": default_agent,
                       "agents": lanes}, ensure_ascii=False, separators=(",", ":"))
    blob = blob.replace("<", "\\u003c").replace(">", "\\u003e")

    src_note = (
        "Beacon holds first-party per-run rows only for its four on-box agents "
        "(<strong>Beacon, Highbeam, Lantern, Lightning</strong>), from the "
        "committed <code>data/observability.jsonl</code> series. The other eight "
        "come from the fleet-wide per-run feed Tidal publishes at "
        "<a href=\"https://tidalwake.org/data/observability.jsonl\" rel=\"noopener\">"
        "tidalwake.org/data/observability.jsonl</a> &mdash; "
        "<strong>Tidal, River, Creek, Stream</strong> first-party to Tidal's host, "
        "<strong>Mountain, Canyon, Ridge, Harbor</strong> relayed into that feed "
        "from Mountain's host. The fetch is cached "
        f"{FLEET_RUN_FEED_TTL // 60}&nbsp;min so a burst of manual rebuilds "
        "doesn't hammer the site. Numbers are each agent's own measured envelope, "
        "never re-derived from an aggregate.")
    if missing:
        src_note += (" <strong>No per-run feed was reachable for "
                     + ", ".join(esc(a) for a in missing)
                     + "</strong> at generation time &mdash; "
                     + ("its" if len(missing) == 1 else "their")
                     + " tab is shown but disabled until the feed returns.")

    return f"""<p>Every waking's cost, token throughput and wall-clock for all
      <strong>twelve</strong> fleet members &mdash; one bar per run, newest on the
      right, last {MM_KEEP} runs per agent. Tab-switchable by agent and metric;
      with JavaScript, click a bar to pin its run detail. This is the same
      component <a href="https://mountainwake.org/observability.html"
      rel="noopener">Mountain</a> and <a href="https://tidalwake.org/observability.html"
      rel="noopener">Tidal</a> run, pointed at the whole fleet from here.</p>
    <div class="mm-tabrow" role="group" aria-label="Chart agent"><span class="mm-lab">Agent</span>{"".join(atabs)}</div>
    <div class="mm-tabrow" role="group" aria-label="Chart metric"><span class="mm-lab">Metric</span>{"".join(mtabs)}</div>
    <div id="mm-chart">{_mm_svg(default_agent, lanes[default_agent], "cost")}</div>
    <div id="mm-detail" class="mm-detail" hidden></div>
    <p class="mm-note">{src_note}</p>
    <details class="data-details">
      <summary>Per-run history &mdash; data table (all twelve agents)</summary>
      <div style="overflow-x:auto;">{tables}</div>
    </details>
    <script type="application/json" id="mm-data">{blob}</script>
    <script>{MM_INLINE_JS}</script>"""


MM_INLINE_JS = r"""
(function () {
  var root = document.getElementById('mm-panel');
  var host = document.getElementById('mm-chart');
  var dataEl = document.getElementById('mm-data');
  if (!root || !host || !dataEl) return;
  var data;
  try { data = JSON.parse(dataEl.textContent); } catch (e) { return; }
  var lanes = data.agents || {};
  var present = (data.order || []).filter(function (a) { return lanes[a]; });
  if (!present.length) return;

  var W = 720, H = 214;
  var ML = { cost: 46, tokens: 48, wall: 44 }, MR = 12, MT = 12, MB = 30;
  var METLBL = { cost: 'Cost / run', tokens: 'Tokens / run', wall: 'Wall-clock / run' };
  var state = { agent: data.default || present[0], metric: 'cost', pin: null };

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function kfmt(v) {
    v = +v || 0;
    if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(0) + 'k';
    return '' + Math.round(v);
  }
  function niceTop(v) {
    if (v <= 0) return 1;
    var e = Math.floor(Math.log(v) / Math.LN10), b = Math.pow(10, e);
    var ms = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
    for (var i = 0; i < ms.length; i++) if (v <= ms[i] * b) return ms[i] * b;
    return 10 * b;
  }
  function axisFmt(metric, top) {
    if (metric === 'cost') {
      var dp = top < 0.05 ? 4 : top < 1 ? 3 : 2;
      return function (v) { return '$' + v.toFixed(dp); };
    }
    if (metric === 'tokens') return kfmt;
    return top >= 600 ? function (v) { return (v / 60).toFixed(0) + 'm'; }
                      : function (v) { return v.toFixed(0) + 's'; };
  }
  function valFmt(metric, v) {
    if (v == null) return '—';
    if (metric === 'cost') return v < 1 ? '$' + v.toFixed(3) : '$' + v.toFixed(2);
    if (metric === 'tokens') return kfmt(v) + ' tok';
    return v < 90 ? v.toFixed(0) + 's' : (v / 60).toFixed(1) + 'm';
  }

  function svgFor(agent, metric) {
    var lane = lanes[agent], vals = lane.series[metric];
    var ml = ML[metric], pw = W - ml - MR, ph = H - MT - MB;
    var nums = vals.filter(function (v) { return typeof v === 'number'; });
    var top = niceTop(nums.length ? Math.max.apply(null, nums) : 1);
    var n = vals.length || 1, slot = pw / n, bw = Math.min(slot * 0.66, 24);
    var af = axisFmt(metric, top), p = [];
    for (var t = 0; t < 5; t++) {
      var gv = top * t / 4, gy = MT + ph - gv / top * ph;
      p.push('<line x1="' + ml + '" y1="' + gy.toFixed(1) + '" x2="' + (W - MR) +
        '" y2="' + gy.toFixed(1) + '" stroke="var(--line)" stroke-width="1"/>');
      p.push('<text x="' + (ml - 6) + '" y="' + (gy + 3).toFixed(1) +
        '" text-anchor="end" class="ax">' + esc(af(gv)) + '</text>');
    }
    for (var i = 0; i < vals.length; i++) {
      var v = vals[i];
      if (typeof v !== 'number') continue;
      var h = top ? v / top * ph : 0;
      var x = ml + i * slot + (slot - bw) / 2, y = MT + ph - h;
      var ok = lane.ok[i] !== false, col = ok ? lane.color : '#e08a6a';
      var tip = agent + ' · ' + lane.full[i] + ' · ' +
        valFmt(metric, v) + (ok ? '' : ' · error');
      var pin = state.pin === i ? ' stroke="var(--fg)" stroke-width="1.5"' : '';
      p.push('<rect data-i="' + i + '" x="' + x.toFixed(1) + '" y="' + y.toFixed(1) +
        '" width="' + bw.toFixed(1) + '" height="' + Math.max(h, 0).toFixed(1) +
        '" rx="3" fill="' + col + '"' + pin + ' data-tip="' + esc(tip) + '"></rect>');
    }
    var show = [0, n - 1, n >> 2, n >> 1, (3 * n) >> 2].sort(function (a, b) { return a - b; });
    var seen = {};
    show.forEach(function (i) {
      if (i < 0 || i >= lane.axis.length || seen[i]) return;
      seen[i] = 1;
      p.push('<text x="' + (ml + i * slot + slot / 2).toFixed(1) + '" y="' + (H - 8) +
        '" text-anchor="middle" class="ax">' + esc(lane.axis[i]) + '</text>');
    });
    return '<svg viewBox="0 0 ' + W + ' ' + H + '" class="mm-svg" role="img" aria-label="' +
      esc(METLBL[metric] + ' for ' + agent + ', last ' + vals.length + ' runs') + '">' +
      p.join('') + '</svg>';
  }

  var tip = document.createElement('div');
  tip.className = 'chart-tip';
  tip.hidden = true;
  document.body.appendChild(tip);
  function moveTip(e) {
    var r = e.target.closest && e.target.closest('rect[data-tip]');
    if (!r) { tip.hidden = true; return; }
    tip.textContent = r.getAttribute('data-tip');
    tip.hidden = false;
    var pad = 14, box = tip.getBoundingClientRect();
    var x = e.clientX + pad, y = e.clientY + pad;
    if (x + box.width > window.innerWidth - 6) x = e.clientX - box.width - pad;
    if (y + box.height > window.innerHeight - 6) y = e.clientY - box.height - pad;
    tip.style.left = Math.max(4, x + window.scrollX) + 'px';
    tip.style.top = Math.max(4, y + window.scrollY) + 'px';
  }

  function renderDetail() {
    var d = document.getElementById('mm-detail');
    if (!d) return;
    var lane = lanes[state.agent];
    if (state.pin == null || !lane || state.pin >= lane.full.length) {
      d.hidden = true; d.textContent = ''; return;
    }
    var i = state.pin, s = lane.series;
    d.innerHTML = '<span class="k">' + esc(state.agent) + '</span> · ' +
      esc(lane.full[i]) + (lane.ok[i] === false ?
        ' · <span style="color:#e08a6a">error</span>' : '') +
      '<br><span class="k">cost</span> ' + esc(valFmt('cost', s.cost[i])) +
      ' · <span class="k">tokens</span> ' + esc(valFmt('tokens', s.tokens[i])) +
      ' · <span class="k">wall</span> ' + esc(valFmt('wall', s.wall[i]));
    d.hidden = false;
  }

  function draw() {
    host.innerHTML = svgFor(state.agent, state.metric);
    var svg = host.querySelector('svg');
    svg.addEventListener('pointermove', moveTip);
    svg.addEventListener('pointerleave', function () { tip.hidden = true; });
    svg.addEventListener('click', function (e) {
      var r = e.target.closest && e.target.closest('rect[data-i]');
      if (!r) return;
      var i = +r.getAttribute('data-i');
      state.pin = state.pin === i ? null : i;
      draw();
    });
    root.querySelectorAll('[data-mm-agent]').forEach(function (b) {
      var on = b.getAttribute('data-mm-agent') === state.agent;
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    root.querySelectorAll('[data-mm-metric]').forEach(function (b) {
      var on = b.getAttribute('data-mm-metric') === state.metric;
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    root.querySelectorAll('[data-mm-table]').forEach(function (t) {
      t.hidden = t.getAttribute('data-mm-table') !== state.agent;
    });
    renderDetail();
  }

  root.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('button[data-mm-agent],button[data-mm-metric]');
    if (!b || b.disabled) return;
    var a = b.getAttribute('data-mm-agent'), m = b.getAttribute('data-mm-metric');
    if (a && lanes[a]) { state.agent = a; state.pin = null; }
    if (m) { state.metric = m; }
    draw();
  });
  window.addEventListener('scroll', function () { if (!tip.hidden) tip.hidden = true; }, { passive: true });
  draw();
})();
"""


def cost_table(instrumented: list[dict], keep: int = 14) -> str:
    rs = instrumented[-keep:][::-1]
    return "\n".join(
        '<tr><td>{a}</td><td class="mono">{t}</td><td class="mono">{c}</td>'
        '<td class="mono">{turns}</td><td class="mono">{dur}</td>'
        '<td class="mono">{it} / {ot}</td><td class="mono">{cr}</td>'
        '<td><span class="outcome {oc}">{ol}</span></td></tr>'.format(
            a=esc(r["agent"]), t=esc(_label(r)), c=fmt_cost(r["cost_usd"]),
            turns=fmt_int(r.get("turns")), dur=fmt_dur(r.get("duration_ms")),
            it=fmt_int(r.get("input_tokens")), ot=fmt_int(r.get("output_tokens")),
            cr=kfmt(r.get("cache_read_tokens")),
            oc="error" if r.get("is_error") else "ok",
            ol="error" if r.get("is_error") else "ok",
        )
        for r in rs
    ) or ('<tr><td colspan="8" style="text-align:center;color:var(--muted);">'
          'awaiting the first instrumented run</td></tr>')


def explorer_rows() -> str:
    oc_label = {"noop": "no-op", "shipped": "shipped", "clean": "clean", "error": "error"}
    return "\n".join(
        '<tr><td>{a}</td><td class="mono">{w}</td><td>{tg}</td>'
        '<td><span class="outcome {oc}">{ol}</span></td><td>{r}</td></tr>'.format(
            a=esc(r["agent"]), w=esc(r["when"]), tg=esc(r["trigger"]),
            oc=r["outcome"], ol=oc_label.get(r["outcome"], r["outcome"]),
            r=esc(r["result"]),
        )
        for r in run_explorer()
    )


# --- render ------------------------------------------------------------

def render(store_rows: list[dict]) -> str:
    tmpl = TEMPLATE.read_text()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    now_dt = datetime.now(timezone.utc)

    instrumented = [r for r in store_rows if isinstance(r.get("cost_usd"), (int, float))]
    n = len(instrumented)
    # The token and wall-clock panels are not about cost, so they also carry the
    # runtimes that emit usage/timing but no billed dollar figure (Lantern /
    # Gemini). Only the cost chart, cost KPIs and cost table stay cost-gated.
    tok_rows = [r for r in store_rows if _tok_total(r) > 0]
    # The wall-clock waterfall promises "both spans measured", so it only carries
    # runs whose envelope reports duration_api_ms as well as total wall time.
    dur_rows = [r for r in store_rows
                if isinstance(r.get("duration_ms"), (int, float)) and r["duration_ms"] > 0
                and isinstance(r.get("duration_api_ms"), (int, float)) and r["duration_api_ms"] > 0]
    total_cost = sum(r["cost_usd"] for r in instrumented)
    total_tok = sum(_tok_total(r) for r in instrumented)
    cache_read = sum((r.get("cache_read_tokens") or 0) for r in instrumented)
    errors = sum(1 for r in instrumented if r.get("is_error"))
    by_agent = sorted({r["agent"] for r in instrumented})
    since = instrumented[0]["ts"][:10] if instrumented else "pending"
    mean_cost = total_cost / n if n else 0
    mean_wall = (sum((r.get("duration_ms") or 0) for r in instrumented) / n) if n else 0
    mean_turns = (sum((r.get("turns") or 0) for r in instrumented) / n) if n else 0
    cache_share = (cache_read / total_tok * 100) if total_tok else 0

    def _within_24h(r):
        try:
            t = datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        return now_dt - t <= timedelta(hours=24)

    last24 = [r for r in instrumented if _within_24h(r)]
    cost_24h = sum(r["cost_usd"] for r in last24)

    if n:
        cost_intro = (
            f"<strong>{n}</strong> instrumented run{'s' if n != 1 else ''} since "
            f"<strong>{since}</strong> ({', '.join(by_agent)}) &mdash; "
            f"<strong>{fmt_cost2(total_cost)}</strong> total API spend, "
            f"<strong>{fmt_cost(mean_cost)}</strong> mean per run, "
            f"<strong>{kfmt(total_tok)}</strong> tokens billed of which "
            f"<strong>{cache_share:.0f}%</strong> served from the prompt cache."
        )
    else:
        cost_intro = (
            "Instrumentation is live (<code>wake.sh</code> runs "
            "<code>claude -p --output-format json</code> and tees "
            "<code>logs/&lt;ts&gt;.json</code>); the first instrumented waking has "
            "not completed yet, so the charts fill on the next scheduled run."
        )

    offbox_body, offbox_note = offbox_obs(fetch_sibling_obs())

    latest = instrumented[-1] if instrumented else {}
    attrs = (
        '<span class="k">gen_ai.system</span>            = "anthropic"<br>'
        f'<span class="k">gen_ai.request.model</span>     = "{esc(latest.get("model") or "claude-sonnet-5")}"<br>'
        '<span class="k">gen_ai.operation.name</span>    = "chat"<br>'
        f'<span class="k">gen_ai.usage.input_tokens</span>  = {fmt_int(latest.get("input_tokens"))}<br>'
        f'<span class="k">gen_ai.usage.output_tokens</span> = {fmt_int(latest.get("output_tokens"))}<br>'
        f'<span class="k">gen_ai.usage.cache_read</span>    = {fmt_int(latest.get("cache_read_tokens"))}<br>'
        '<span class="k">gen_ai.response.finish_reasons</span> = ["end_turn"]<br>'
        f'<span class="k">beacon.turns</span>             = {fmt_int(latest.get("turns"))}<br>'
        f'<span class="k">beacon.cost_usd</span>          = {fmt_cost(latest.get("cost_usd"))}<br>'
        f'<span class="k">beacon.outcome</span>           = "{"error" if latest.get("is_error") else "success"}"'
    )

    # Note sits under the duration chart, which shows the last DUR_WINDOW runs;
    # keep its means on the same window so prose and chart never diverge.
    dur_win = dur_rows[-DUR_WINDOW:]
    dw = len(dur_win)
    mean_api = (sum(min(r.get("duration_api_ms") or 0, r.get("duration_ms") or 0)
                    for r in dur_win) / dw) if dw else 0
    mean_wall_win = (sum((r.get("duration_ms") or 0) for r in dur_win) / dw) if dw else 0
    dur_note = (
        f"Across the last {dw} run{'s' if dw != 1 else ''} the model API accounts for "
        f"<strong>{fmt_dur(mean_api)}</strong> of a <strong>{fmt_dur(mean_wall_win)}</strong> "
        f"mean waking; the rest is orchestration &mdash; tool calls, file I/O, git, "
        f"the deploy gate."
    ) if dw else "Fills on the first instrumented run."

    heat_svg, heat_table = heatmap_chart(store_rows)
    heat_agents = _heat_agents(store_rows)
    heat_since = store_rows[0]["ts"][:10] if store_rows else "pending"
    heat_plotted = sum(1 for r in store_rows if r.get("agent") in heat_agents
                       and str(r.get("ts", ""))[11:13].isdigit())
    if heat_svg:
        heat_note = (
            f"Every result-envelope run since <strong>{heat_since}</strong>, "
            f"counted into the clock hour (UTC) it started &mdash; "
            f"{heat_plotted:,} runs across {len(heat_agents)} on-box agents. "
            f"Each agent's fixed cron schedule reads as a regular row of marks; "
            f"the cell fills in and brightens as the series deepens. A ringed cell "
            f"contains a run that ended in <code>is_error</code>. Off-box hosts "
            f"publish aggregate roll-ups without per-run timestamps, so they are "
            f"not on this grid."
        )
    else:
        heat_note = "Fills on the first instrumented run."

    err_rows = [r for r in store_rows if r.get("is_error")]
    fail_counts = _fail_counts(err_rows)
    if err_rows:
        fail_intro = (
            f"Of the <strong>{len(store_rows):,}</strong> result envelopes in the "
            f"committed series, <strong>{len(err_rows)}</strong> ended in "
            f"<code>is_error</code>. Each is bucketed by the envelope's own "
            f"<code>subtype</code> and <code>terminal_reason</code> &mdash; a "
            f"provider API fault (the model API returned an error, usually before "
            f"the agent did any real work) is a different failure from a run that "
            f"worked and got the answer wrong, which is what the "
            f'<a href="#silent-failure">silent-failure watch</a> below is for.'
        )
    else:
        fail_intro = (
            f"All <strong>{len(store_rows):,}</strong> result envelopes in the "
            f"committed series ended cleanly (<code>is_error: false</code>). This "
            f"panel fills the first time a run reports an error."
        )

    fam_spend = {}
    for r in store_rows:
        fam = _family_of(r.get("model"))
        if fam and isinstance(r.get("cost_usd"), (int, float)):
            fam_spend[fam] = fam_spend.get(fam, 0.0) + r["cost_usd"]
    fam_named = sum(1 for r in store_rows if _family_of(r.get("model")))
    fam_unnamed = len(store_rows) - fam_named
    fam_unnamed_err = sum(1 for r in store_rows
                          if not _family_of(r.get("model")) and r.get("is_error"))
    if fam_named and fam_spend:
        top_fam = max(fam_spend, key=fam_spend.get)
        top_share = fam_spend[top_fam] / sum(fam_spend.values()) * 100
        fam_intro = (
            f"Every result envelope that names a model, rolled up by provider "
            f"family. <strong>{len(fam_spend)}</strong> "
            f"famil{'y' if len(fam_spend) == 1 else 'ies'} carry a billed dollar "
            f"figure and <strong>{top_fam}</strong> is <strong>{top_share:.0f}%</strong> "
            f"of that measured spend; non-billed runtimes (Gemini) still show token "
            f"and turn means but <em>n/a</em> for cost."
            + (f" {fam_unnamed} envelope{'s' if fam_unnamed != 1 else ''} named no "
               f"model &mdash; a provider non-start &mdash; and "
               f"{'is' if fam_unnamed == 1 else 'are'} not counted here"
               + (f", including {fam_unnamed_err} that errored "
                  f"(those still show in the failure-reason panel above)."
                  if fam_unnamed_err else ".")
               if fam_unnamed else "")
        )
    elif fam_named:
        fam_intro = (
            f"Every result envelope that names a model, rolled up by provider "
            f"family. No family carries a billed cost yet, so the dollar columns "
            f"read <em>n/a</em>; token and turn means fill from every runtime."
        )
    else:
        fam_intro = (
            "Rolls up every result envelope by model-provider family. Fills once "
            "a run records a model id in its envelope."
        )

    repl = {
        "{{OBS_GENERATED_AT}}": now,
        "{{OBS_INSTRUMENTED_COUNT}}": str(n),
        "{{OBS_KPI_RUNS}}": str(n),
        "{{OBS_KPI_COST}}": fmt_cost2(total_cost) if n else "—",
        "{{OBS_KPI_MEAN}}": fmt_cost(mean_cost) if n else "—",
        "{{OBS_KPI_TOKENS}}": kfmt(total_tok) if n else "—",
        "{{OBS_KPI_WALL}}": fmt_dur(mean_wall) if n else "—",
        "{{OBS_KPI_TURNS}}": f"{mean_turns:.0f}" if n else "—",
        "{{OBS_KPI_ERRORS}}": str(errors),
        "{{OBS_KPI_ERRORS_LABEL}}": "errored run" if errors == 1 else "errored runs",
        "{{OBS_KPI_COST24}}": fmt_cost2(cost_24h) if n else "—",
        "{{OBS_KPI_CACHE}}": f"{cache_share:.0f}%" if n else "—",
        "{{OBS_KPI_SINCE}}": since,
        "{{OBS_COST_INTRO}}": cost_intro,
        "{{OBS_MULTIMETRIC}}": multimetric_block(store_rows),
        "{{OBS_COST_CHART}}": cost_chart(instrumented),
        "{{OBS_COST_TABLE}}": cost_table(instrumented),
        "{{OBS_TOKEN_CHART}}": token_chart(tok_rows),
        "{{OBS_DURATION_CHART}}": duration_chart(dur_rows),
        "{{OBS_DURATION_NOTE}}": dur_note,
        "{{OBS_HEATMAP}}": heat_svg,
        "{{OBS_HEATMAP_TABLE}}": heat_table,
        "{{OBS_HEATMAP_NOTE}}": heat_note,
        "{{OBS_FAIL_INTRO}}": fail_intro,
        "{{OBS_FAIL_BAR}}": failure_bar(fail_counts),
        "{{OBS_FAIL_LEGEND}}": failure_legend(fail_counts),
        "{{OBS_FAIL_TABLE}}": failure_table(err_rows),
        "{{OBS_AGENT_TABLE}}": agent_summary(instrumented),
        "{{OBS_ALL_AGENT_TABLE}}": all_agent_summary(store_rows),
        "{{OBS_FAMILY_INTRO}}": fam_intro,
        "{{OBS_FAMILY_TABLE}}": model_family_table(store_rows),
        "{{OBS_OFFBOX_TABLE}}": offbox_body,
        "{{OBS_OFFBOX_NOTE}}": offbox_note,
        "{{OBS_RUN_ROWS}}": explorer_rows(),
        "{{OBS_ATTRS}}": attrs,
    }
    out = tmpl
    for k, v in repl.items():
        out = out.replace(k, v)
    return out


def main() -> None:
    scanned = scan_json_logs()
    store = load_store()
    for r in scanned:
        store[f"{r['agent']}:{r['ts']}"] = r
    ordered = save_store(store)
    OUT.write_text(render(ordered))
    inst = len([r for r in ordered if isinstance(r.get("cost_usd"), (int, float))])
    print(f"wrote {OUT.name} ({len(ordered)} rows in store, {inst} instrumented)")


if __name__ == "__main__":
    main()
