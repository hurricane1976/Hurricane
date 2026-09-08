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
}

AMBER = "#ff8a3d"
TEAL = "#4fd1c5"
BLUE = "#8ea0c8"
VIOLET = "#9b8cff"
SLATE = "#5b6472"
AGENT_COLOR = {"Beacon": AMBER, "Highbeam": TEAL, "Lantern": VIOLET, "Lightning": SLATE}
CHART_W = 720


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
                    f'{esc(r["agent"][:1])} {esc(_label(r))}</text>')
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
                    nm, f"{host}&rsquo;s host", sk,
                    (avg_c * sk) if isinstance(avg_c, (int, float)) else None, avg_c,
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
                 "(Canyon, Ridge, Harbor) publish an empty roll-up so far and "
                 "appear here once each crosses that host&rsquo;s sample gate.")
    note += (" Tidal&rsquo;s dashboard is HTML-only so far, with no JSON roll-up "
             "to consume.")
    body = "\n".join(rows) or (
        '<tr><td colspan="9" style="text-align:center;color:var(--muted);">'
        'no host has crossed its sample gate yet</td></tr>')
    return body, note


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
    dur_win = instrumented[-DUR_WINDOW:]
    dw = len(dur_win)
    mean_api = (sum(min(r.get("duration_api_ms") or 0, r.get("duration_ms") or 0)
                    for r in dur_win) / dw) if dw else 0
    mean_wall_win = (sum((r.get("duration_ms") or 0) for r in dur_win) / dw) if dw else 0
    dur_note = (
        f"Across the last {dw} run{'s' if dw != 1 else ''} the model API accounts for "
        f"<strong>{fmt_dur(mean_api)}</strong> of a <strong>{fmt_dur(mean_wall_win)}</strong> "
        f"mean waking; the rest is orchestration &mdash; tool calls, file I/O, git, "
        f"the deploy gate."
    ) if n else "Fills on the first instrumented run."

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
        "{{OBS_COST_CHART}}": cost_chart(instrumented),
        "{{OBS_COST_TABLE}}": cost_table(instrumented),
        "{{OBS_TOKEN_CHART}}": token_chart(instrumented),
        "{{OBS_DURATION_CHART}}": duration_chart(instrumented),
        "{{OBS_DURATION_NOTE}}": dur_note,
        "{{OBS_AGENT_TABLE}}": agent_summary(instrumented),
        "{{OBS_ALL_AGENT_TABLE}}": all_agent_summary(store_rows),
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
