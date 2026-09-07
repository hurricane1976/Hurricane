#!/usr/bin/env python3
"""Regenerates website/observability.html -- the fleet's agentic-observability
dashboard, in the shape Dash0's Agent0 draws it (an agent run is a trace; runs
are rows; token + cost tied to the outcome).

Every number here is measured at generation time:

* **Per-run cost / tokens / turns / duration** come from the JSON result
  envelope `claude -p --output-format json` writes to `logs/<ts>.json` on each
  waking (wired into wake.sh). Beacon and Highbeam (both Claude Code) emit it;
  Lantern (Gemini CLI) and Lightning (opencode) do not yet, so their lanes show
  "runtime not instrumented" rather than a fabricated number.
* **The run explorer** (runs as rows) is merged from Beacon's git commits and
  the shared fleet timeline `shared/LOG.md`.

The instrumented per-run metrics are also rolled up into
`website/data/observability.jsonl` (committed) so the series survives the
30-day pruning of `logs/`. That file holds only non-sensitive counters --
never the `.result` transcript text.

Run standalone or via deploy.sh. `/api/observability` serves the same roll-up.
"""
import json
import re
import subprocess
from datetime import datetime, timezone
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


def _iso_from_ts(ts: str) -> str:
    """20260907T040233Z -> 2026-09-07T04:02:33Z"""
    return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[9:11]}:{ts[11:13]}:{ts[13:15]}Z"


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
                "duration_ms": env.get("duration_ms"),
                "duration_api_ms": env.get("duration_api_ms"),
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


def save_store(rows: dict) -> None:
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
    # de-dupe near-identical (same agent + same day + same first 40 chars)
    seen, uniq = set(), []
    for r in sorted(merged, key=lambda r: r["when"], reverse=True):
        key = (r["agent"], r["when"][:10], r["result"][:40].lower())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq[:limit]


# --- rendering ---------------------------------------------------------------

def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def fmt_cost(v) -> str:
    return f"${v:,.4f}" if isinstance(v, (int, float)) else "—"


def fmt_int(v) -> str:
    return f"{v:,}" if isinstance(v, (int, float)) else "—"


def fmt_dur(ms) -> str:
    if not isinstance(ms, (int, float)):
        return "—"
    s = ms / 1000
    return f"{s:.0f}s" if s < 90 else f"{s / 60:.1f}m"


def render(store_rows: list[dict]) -> str:
    tmpl = TEMPLATE.read_text()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    instrumented = [r for r in store_rows if isinstance(r.get("cost_usd"), (int, float))]
    n = len(instrumented)
    total_cost = sum(r["cost_usd"] for r in instrumented)
    total_tok = sum((r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
                    + (r.get("cache_read_tokens") or 0) + (r.get("cache_creation_tokens") or 0)
                    for r in instrumented)
    since = instrumented[0]["ts"][:10] if instrumented else None
    by_agent = sorted({r["agent"] for r in instrumented})

    if instrumented:
        cost_intro = (
            f"<strong>{n}</strong> instrumented run{'s' if n != 1 else ''} "
            f"since <strong>{since}</strong> "
            f"({', '.join(by_agent)}) &mdash; "
            f"<strong>{fmt_cost(total_cost)}</strong> total, "
            f"<strong>{fmt_cost(total_cost / n)}</strong> mean, "
            f"<strong>{fmt_int(total_tok)}</strong> tokens (incl. cache)."
        )
        recent = instrumented[-12:][::-1]
        cost_rows = "\n".join(
            "<tr><td>{a}</td><td class=\"mono\">{t}</td><td class=\"mono\">{c}</td>"
            "<td class=\"mono\">{turns}</td><td class=\"mono\">{dur}</td>"
            "<td class=\"mono\">{it} in / {ot} out</td>"
            "<td class=\"mono\">{cr} cache-rd</td>"
            "<td><span class=\"outcome {oc}\">{ol}</span></td></tr>".format(
                a=esc(r["agent"]), t=esc(r["ts"][5:16].replace("T", " ")),
                c=fmt_cost(r["cost_usd"]), turns=fmt_int(r.get("turns")),
                dur=fmt_dur(r.get("duration_ms")),
                it=fmt_int(r.get("input_tokens")), ot=fmt_int(r.get("output_tokens")),
                cr=fmt_int(r.get("cache_read_tokens")),
                oc="error" if r.get("is_error") else "shipped",
                ol="error" if r.get("is_error") else "ok",
            )
            for r in recent
        )
        # cost bars, newest-right, scaled to the max in the window
        window = instrumented[-16:]
        cmax = max((r["cost_usd"] for r in window), default=0) or 1
        cost_bars = "\n".join(
            "<span class=\"cb-l\">{lbl}</span><div class=\"cb-t\">"
            "<div class=\"cb-b real\" style=\"width:{w:.0f}%\" title=\"{c}\"></div></div>".format(
                lbl=esc(r["ts"][5:16].replace("T", " ")),
                w=max(3, r["cost_usd"] / cmax * 100), c=fmt_cost(r["cost_usd"]),
            )
            for r in window
        )
        cost_flag = "live"
        cost_flag_label = "Live"
    else:
        cost_intro = (
            "Instrumentation is <strong>live as of this deploy</strong> "
            "(<code>wake.sh</code> now runs <code>claude -p --output-format json</code> "
            "and tees <code>logs/&lt;ts&gt;.json</code>) &mdash; the first instrumented "
            "waking has not completed yet, so there is nothing to chart. This panel "
            "fills on the next scheduled run."
        )
        cost_rows = ("<tr><td colspan=\"8\" style=\"color:var(--muted);text-align:center;\">"
                     "awaiting the first instrumented run</td></tr>")
        cost_bars = ""
        cost_flag = "live"
        cost_flag_label = "Live &mdash; filling"

    oc_label = {"noop": "no-op", "shipped": "shipped", "clean": "clean", "error": "error"}
    ex_rows = "\n".join(
        "<tr><td>{a}</td><td class=\"mono\">{w}</td><td>{tg}</td>"
        "<td><span class=\"outcome {oc}\">{ol}</span></td><td>{r}</td></tr>".format(
            a=esc(r["agent"]), w=esc(r["when"]), tg=esc(r["trigger"]),
            oc=r["outcome"], ol=oc_label.get(r["outcome"], r["outcome"]), r=esc(r["result"]),
        )
        for r in run_explorer()
    )

    repl = {
        "{{OBS_GENERATED_AT}}": now,
        "{{OBS_COST_INTRO}}": cost_intro,
        "{{OBS_COST_ROWS}}": cost_rows,
        "{{OBS_COST_BARS}}": cost_bars,
        "{{OBS_COST_FLAG}}": cost_flag,
        "{{OBS_COST_FLAG_LABEL}}": cost_flag_label,
        "{{OBS_RUN_ROWS}}": ex_rows,
        "{{OBS_INSTRUMENTED_COUNT}}": str(n),
        "{{OBS_KPI_RUNS}}": str(n),
        "{{OBS_KPI_COST}}": fmt_cost(total_cost) if instrumented else "—",
        "{{OBS_KPI_MEAN}}": fmt_cost(total_cost / n) if instrumented else "—",
        "{{OBS_KPI_TOKENS}}": fmt_int(total_tok) if instrumented else "—",
        "{{OBS_KPI_SINCE}}": since or "pending",
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
    print(f"wrote {OUT.name} ({len(ordered)} rows in store, "
          f"{len([r for r in ordered if isinstance(r.get('cost_usd'), (int, float))])} instrumented)")


if __name__ == "__main__":
    main()
