#!/usr/bin/env python3
"""fleet-telemetry/v1 write side for Beacon (see
shared/outbox/fleet-telemetry-schema-w333/SCHEMA.md, LOCKED w334).

Called by wake.sh after the `claude --output-format json` envelope is parsed:

    python3 fleet_telemetry.py <envelope.json> <TS> <claude_exit>

Appends one NDJSON envelope (non-sensitive counters only -- never `.result`,
never prompt text) to website/data/fleet-telemetry.jsonl, the stable per-host
feed served at https://www.beaconwake.com/data/fleet-telemetry.jsonl. Oldest
first, newest last; rolling window of max(90 days, 1000 lines). Idempotent on
`agent:ts` so a re-run of the same waking replaces rather than duplicates.

Runs unconditionally (including on a non-zero claude exit) so error / timeout
wakings still land a row -- those are the ones the cross-host panel most wants.
Never fatal: any problem here prints a note and exits 0 so it cannot break
wake.sh.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.abspath(__file__))
FEED = os.environ.get(
    "FLEET_TELEMETRY_FEED",
    os.path.join(REPO, "website", "data", "fleet-telemetry.jsonl"),
)
NOTES = os.path.join(REPO, "NOTES.md")

AGENT = "beacon"
HOST = "beacon"
KEEP_DAYS = 90
KEEP_LINES = 1000

FAMILY_BY_PREFIX = (
    ("claude", "claude"),
    ("gemini", "gemini"),
    ("glm", "glm"),
    ("deepseek", "deepseek"),
)


def model_family(model: str) -> str:
    m = (model or "").lower()
    for prefix, fam in FAMILY_BY_PREFIX:
        if m.startswith(prefix) or prefix in m:
            return fam
    return "claude"  # Beacon only ever runs Claude Code


def canonical_model(env: dict) -> str | None:
    """The model that did the run's real work -- rank modelUsage by spend, then
    by total billed tokens (matches website/build_observability.py:_canonical_model
    so the two stores join on the same value)."""
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


def waking_count() -> int | None:
    try:
        text = open(NOTES).read()
    except OSError:
        return None
    nums = [int(n) for n in re.findall(r"(\d+)(?:st|nd|rd|th) waking", text)]
    nums += [int(n) for n in re.findall(r"(?m)^#+\s+w(\d{2,4})\b", text)]
    return max(nums) if nums else None


def iso_from_ts(stamp: str) -> str:
    """20260909T120002Z -> 2026-09-09T12:00:02Z (same as build_observability)."""
    m = re.match(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", stamp or "")
    if not m:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    y, mo, d, h, mi, s = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}Z"


def classify(exit_code: int, env: dict) -> str:
    """subtype / exit -> terminal_reason enum, per SCHEMA.md v7 table."""
    if exit_code in (124, 137):
        return "timeout"
    subtype = str(env.get("subtype") or "").lower()
    if any(t in subtype for t in ("overloaded", "api_error", "rate_limit", "529", "503", "502")):
        return "provider_api_error"
    if subtype == "error_max_turns":
        return "turn_limit"
    if subtype == "error_during_execution":
        return "execution_error"
    # A non-zero shell exit is a host/tool fault regardless of what the envelope
    # says (SCHEMA.md v7: "non-zero wake.sh exit (127, tool/host fault)").
    if exit_code not in (0, None):
        return "execution_error"
    if subtype == "success":
        return "completed"
    if env.get("is_error"):
        return "other"
    if not env:
        return "execution_error"  # exit 0 but no parseable envelope: treat as fault
    return "completed"


def build_envelope(env: dict, stamp: str, exit_code: int) -> dict:
    u = env.get("usage") or {}
    model = canonical_model(env)
    cost = env.get("total_cost_usd")
    cost = float(cost) if isinstance(cost, (int, float)) else None
    dur = env.get("duration_ms")
    if not isinstance(dur, (int, float)):
        dur = 0
    api_ms = env.get("duration_api_ms")
    return {
        "schema": "fleet-telemetry/v1",
        "agent": AGENT,
        "host": HOST,
        "ts": iso_from_ts(stamp),
        "waking_count": waking_count(),
        "model": model or "claude-sonnet-5",
        "model_family": model_family(model),
        "cost_usd": round(cost, 7) if cost is not None else None,
        "cost_estimated": False,  # Beacon runs billed Claude Code only
        "input_tokens": u.get("input_tokens"),
        "output_tokens": u.get("output_tokens"),
        "cache_read_tokens": u.get("cache_read_input_tokens"),
        "cache_creation_tokens": u.get("cache_creation_input_tokens"),
        "duration_ms": int(dur),
        "duration_api_ms": int(api_ms) if isinstance(api_ms, (int, float)) else None,
        "turns": env.get("num_turns"),
        "is_error": bool(env.get("is_error")) or exit_code not in (0, None),
        "terminal_reason": classify(exit_code, env),
        "subtype": env.get("subtype"),
    }


def load_feed() -> list[dict]:
    rows = []
    try:
        with open(FEED) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return rows


def trim(rows: list[dict]) -> list[dict]:
    rows.sort(key=lambda r: (r.get("ts") or "", r.get("agent") or ""))
    if len(rows) <= KEEP_LINES:
        return rows
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    keep_by_age = [r for r in rows if (r.get("ts") or "") >= cutoff]
    # max(90 days, 1000 lines): keep whichever set is larger
    return keep_by_age if len(keep_by_age) >= KEEP_LINES else rows[-KEEP_LINES:]


def main():
    envelope_path = sys.argv[1] if len(sys.argv) > 1 else ""
    stamp = sys.argv[2] if len(sys.argv) > 2 else ""
    try:
        exit_code = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    except ValueError:
        exit_code = 0

    env = {}
    if envelope_path and os.path.isfile(envelope_path) and os.path.getsize(envelope_path) > 0:
        try:
            loaded = json.load(open(envelope_path))
            if isinstance(loaded, dict) and loaded.get("type") == "result":
                env = loaded
        except (OSError, ValueError) as e:
            print(f"(fleet_telemetry: could not parse envelope: {e})")

    row = build_envelope(env, stamp, exit_code)
    rows = [r for r in load_feed()
            if not (r.get("agent") == row["agent"] and r.get("ts") == row["ts"])]
    rows.append(row)
    rows = trim(rows)

    os.makedirs(os.path.dirname(FEED), exist_ok=True)
    tmp = FEED + ".tmp"
    with open(tmp, "w") as fh:
        fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    os.replace(tmp, FEED)
    print(f"(fleet_telemetry: wrote row ts={row['ts']} "
          f"reason={row['terminal_reason']} cost={row['cost_usd']}; feed {len(rows)} lines)")


if __name__ == "__main__":
    main()
