#!/usr/bin/env python3
"""Transform an opencode `run --format json` session into an observability envelope.

Beacon runs on opencode + DeepSeek V4 Pro (via OpenRouter) as of
Beacon's ~355th waking (2026-09-15); before that Claude Code
(`claude --model sonnet`). `wake.sh` streams opencode's structured
JSON events to a raw file; this script pulls the session id out of that
stream, asks `opencode export <id>` for the authoritative per-session
cost / token totals, and writes a result envelope (`logs/<ts>.json`)
matching the schema read by `fleet_telemetry.py`, `spend_check.py`,
`record_observability_row.py`, and `website/build_observability.py`.
It also folds the assistant transcript + a one-line metrics summary into
`logs/<ts>.log`.

usage: format_envelope.py <raw_json> <envelope_file> <log_file> <exit_code> [duration_ms]
"""

import json
import os
import subprocess
import sys
from pathlib import Path

CANONICAL_MODEL_FALLBACK = "deepseek-v4-pro"


def _iter_events(raw_text: str):
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except Exception:
            continue


def _session_id(events) -> str | None:
    for ev in events:
        sid = ev.get("sessionID") or (ev.get("part") or {}).get("sessionID")
        if sid:
            return sid
    return None


def _export(session_id: str) -> dict:
    path = os.environ.get("PATH", "")
    for cand in ("opencode",):
        try:
            out = subprocess.run(
                [cand, "export", session_id],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "PATH": path},
            )
            if out.returncode == 0 and out.stdout.strip():
                return json.loads(out.stdout)
        except Exception:
            pass
    return {}


def _totals_from_events(raw_text: str) -> dict:
    """Fallback when `opencode export` is unavailable: sum step_finish events."""
    cost = 0.0
    inp = outp = reason = cache_r = cache_w = 0
    for ev in _iter_events(raw_text):
        if ev.get("type") != "step_finish":
            continue
        part = ev.get("part") or {}
        tk = part.get("tokens") or {}
        cost += part.get("cost") or 0.0
        inp += tk.get("input") or 0
        outp += tk.get("output") or 0
        reason += tk.get("reasoning") or 0
        c = tk.get("cache") or {}
        cache_r += c.get("read") or 0
        cache_w += c.get("write") or 0
    return {
        "cost": cost or None,
        "tokens": {
            "input": inp, "output": outp, "reasoning": reason,
            "cache": {"read": cache_r, "write": cache_w},
        },
        "model": {"id": CANONICAL_MODEL_FALLBACK},
    }


def _transcript_from_events(raw_text: str) -> str:
    chunks = []
    for ev in _iter_events(raw_text):
        if ev.get("type") != "text":
            continue
        part = ev.get("part") or {}
        txt = part.get("text")
        if txt:
            chunks.append(txt)
    return "\n".join(chunks).strip()


def main() -> None:
    if len(sys.argv) < 5:
        print(f"usage: {sys.argv[0]} <raw_json> <envelope_file> <log_file> <exit_code> [duration_ms]",
              file=sys.stderr)
        sys.exit(1)

    raw_file = Path(sys.argv[1])
    envelope_file = Path(sys.argv[2])
    log_file = Path(sys.argv[3])
    try:
        exit_code = int(sys.argv[4])
    except ValueError:
        exit_code = 1
    duration_ms = 0
    if len(sys.argv) >= 6:
        try:
            duration_ms = int(sys.argv[5])
        except ValueError:
            duration_ms = 0

    is_error = (exit_code != 0)
    subtype = "error" if is_error else "success"
    if exit_code in (124, 137):
        subtype = "timeout"

    raw_text = ""
    if raw_file.exists() and raw_file.stat().st_size > 0:
        raw_text = raw_file.read_text(encoding="utf-8", errors="replace")

    events = list(_iter_events(raw_text))
    session_id = _session_id(events)

    info = {}
    if session_id:
        exported = _export(session_id)
        info = exported.get("info") or {}
        messages = exported.get("messages") or []
        assistant_msgs = [m for m in messages if (m.get("info") or {}).get("role") == "assistant"]
        num_turns = len(assistant_msgs)
    else:
        num_turns = 0

    if not info:
        info = _totals_from_events(raw_text)
        num_turns = num_turns or sum(1 for ev in events if ev.get("type") == "step_finish")

    tokens = info.get("tokens") or {}
    cache = tokens.get("cache") or {}
    input_tokens = tokens.get("input") or 0
    output_tokens = (tokens.get("output") or 0) + (tokens.get("reasoning") or 0)
    cache_read = cache.get("read") or 0
    cache_write = cache.get("write") or 0
    cost = info.get("cost")
    canonical_model = (info.get("model") or {}).get("id") or CANONICAL_MODEL_FALLBACK

    # A provider-side rate limit / 5xx that killed the run: surface it distinctly.
    if is_error and subtype == "error":
        low = raw_text.lower()
        if any(t in low for t in ("rate limit", "rate_limit", "overloaded", "429",
                                  "resource_exhausted", "503", "502", "500 internal")):
            subtype = "provider_api_error"

    envelope = {
        "type": "result",
        "subtype": subtype,
        "is_error": bool(is_error),
        "total_cost_usd": cost,
        "num_turns": num_turns,
        "duration_ms": duration_ms,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write,
        },
        "modelUsage": {
            "Beacon": {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "cacheReadInputTokens": cache_read,
                "cacheCreationInputTokens": cache_write,
                "costUSD": cost,
                "canonicalModel": canonical_model,
            }
        },
    }

    envelope_file.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")

    transcript = _transcript_from_events(raw_text) or "(no assistant text captured in the event stream)"
    with log_file.open("a", encoding="utf-8") as f:
        f.write("\n" + transcript + "\n\n")
        f.write("--- run metrics (opencode run --format json + opencode export) ---\n")
        f.write(
            "cost_usd={} turns={} duration_ms={} in_tok={} out_tok={} "
            "cache_read={} cache_write={} model={} session={} is_error={} subtype={}\n".format(
                cost, num_turns, duration_ms, input_tokens, output_tokens,
                cache_read, cache_write, canonical_model, session_id, is_error, subtype,
            )
        )


if __name__ == "__main__":
    main()