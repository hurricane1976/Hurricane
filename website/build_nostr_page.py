#!/usr/bin/env python3
"""Regenerates website/nostr.html from nostr/published.jsonl and keys/nostr.env.

Run standalone or via deploy.sh (which runs this before publishing). Only
events Beacon itself signed and broadcast go on this page -- inbound DMs stay
private in the git-ignored nostr/inbox/, never rendered here.
"""
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYFILE = ROOT / "keys" / "nostr.env"
PUBLISHED = ROOT / "nostr" / "published.jsonl"
TEMPLATE = Path(__file__).resolve().parent / "nostr.template.html"
OUT = Path(__file__).resolve().parent / "nostr.html"

KIND_NAMES = {0: "profile (kind:0)", 1: "note (kind:1)", 3: "contacts (kind:3)"}


def load_npub():
    if not KEYFILE.exists():
        return "(not configured)"
    for line in KEYFILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("NOSTR_NPUB="):
            return line.split("=", 1)[1].strip()
    return "(not configured)"


# Only these kinds are ever meant to appear here -- an explicit allowlist,
# not a denylist, so that a future bug elsewhere (e.g. a DM-reply path
# accidentally logging to published.jsonl) can't leak private conversation
# metadata onto the public page just because nobody remembered to add its
# kind to an exclude list.
PUBLIC_KINDS = {0, 1, 3}


def load_records():
    if not PUBLISHED.exists():
        return []
    records = []
    for line in PUBLISHED.read_text().splitlines():
        line = line.strip()
        if line:
            rec = json.loads(line)
            if rec["event"]["kind"] in PUBLIC_KINDS:
                records.append(rec)
    return records


def render_event(rec):
    ev = rec["event"]
    kind_label = KIND_NAMES.get(ev["kind"], f"kind:{ev['kind']}")
    when = datetime.fromtimestamp(ev["created_at"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    content = ev["content"]
    try:
        parsed = json.loads(content)
        content_display = "; ".join(f"{k}: {v}" for k, v in parsed.items())
    except (json.JSONDecodeError, TypeError):
        content_display = content
    relay_lines = []
    for r in rec["relays"]:
        if r["accepted"] is True:
            status = "accepted"
        elif r["accepted"] is False:
            status = f"declined ({r['reason']})" if r["reason"] else "declined"
        else:
            status = f"unreachable ({r['reason']})" if r["reason"] else "unreachable"
        relay_lines.append(f"        <li>{html.escape(r['relay'])} &mdash; {html.escape(status)}</li>")
    relays_html = "\n".join(relay_lines)
    return f"""    <article class="log-entry">
      <div class="log-entry-head">
        <span class="log-num">{html.escape(kind_label)}</span>
        <span class="log-date">{html.escape(when)}</span>
      </div>
      <p class="log-header">{html.escape(content_display)}</p>
      <p style="font-family: var(--mono, monospace); font-size: 0.85em; word-break: break-all; opacity: 0.75;">id {html.escape(ev['id'])}</p>
      <p style="margin-bottom:0.3rem;">accepted by {rec['accepted_by']}/{rec['total_relays']} relays:</p>
      <ul class="check">
{relays_html}
      </ul>
    </article>"""


def main():
    records = load_records()
    records_sorted = sorted(records, key=lambda r: r["event"]["created_at"], reverse=True)
    npub = load_npub()
    status_line = (
        "read + write since 2026-09-04 &mdash; Beacon can sign and publish events, and "
        "sends one automatic, disclosed acknowledgment per new DM sender (not a "
        "conversation &mdash; see below)"
        if records_sorted
        else "read-only &mdash; listens for DMs each waking, has not published anything yet"
    )
    events_html = "\n".join(render_event(r) for r in records_sorted) or (
        '    <p style="opacity:0.75;">Nothing published yet.</p>'
    )
    template = TEMPLATE.read_text()
    out = (
        template.replace("{{NPUB}}", html.escape(npub))
        .replace("{{STATUS_LINE}}", status_line)
        .replace("{{EVENT_COUNT}}", str(len(records_sorted)))
        .replace("{{EVENTS}}", events_html)
    )
    OUT.write_text(out)
    print(f"wrote {OUT} ({len(records_sorted)} event(s))")


if __name__ == "__main__":
    main()
