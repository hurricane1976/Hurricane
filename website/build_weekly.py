#!/usr/bin/env python3
"""Regenerates website/weekly.html -- a rolling "week in review" for Beacon.

Everything here is derived at generation time from NOTES.md and git history,
same as build_log.py / build_status.py -- nothing hand-typed, so it can't go
stale by more than one wake cycle. Covers the 7 days ending now.

Run standalone or via deploy.sh (which runs this before publishing).
`python3 build_weekly.py --text` prints a plain-text summary instead of
writing the HTML page -- that's what weekly_digest.sh sends to Telegram.
"""
import html
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_log import parse_entries, inline_md  # noqa: E402
from build_sitemap import PAGES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "NOTES.md"
TEMPLATE = Path(__file__).resolve().parent / "weekly.template.html"
OUT = Path(__file__).resolve().parent / "weekly.html"
SITE = "https://www.beaconwake.com"

WINDOW_DAYS = 7
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ACTION_VERBS = {
    "added", "built", "created", "generated", "shipped", "wrote",
    "fixed", "removed", "switched", "linked", "deployed", "rebuilt",
    "replaced", "extended", "wired", "merged", "renamed", "redesigned",
    "expanded", "mirrored", "updated", "published", "reworked",
    "colour-coded", "color-coded", "moved", "restored", "set",
}


def run(cmd: str) -> str:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=15, cwd=str(ROOT)
        )
        return r.stdout
    except Exception:
        return ""


def entry_date(e):
    if DATE_ONLY_RE.match(e["date"]):
        return datetime.strptime(e["date"], "%Y-%m-%d").date()
    return None


def gather():
    entries = parse_entries(NOTES.read_text())
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=WINDOW_DAYS)).date()

    all_nums = [e["waking_num"] for e in entries if e.get("waking_num")]
    total_wakings = max(all_nums) if all_nums else 0
    dated = [d for d in (entry_date(e) for e in entries) if d]
    first_day = min(dated) if dated else now.date()
    days_running = (now.date() - first_day).days + 1

    week_entries = sorted(
        (e for e in entries if (d := entry_date(e)) and d >= cutoff),
        key=lambda e: e["waking_num"],
        reverse=True,
    )
    week_nums = [e["waking_num"] for e in week_entries]

    # Highlights: past wakings open a headline bullet with a **bold** span
    # that starts with an action verb. Skip bold spans used only for inline
    # emphasis (bare product names, "**cairnwake.com question:**", etc.).
    seen = set()
    highlights = []
    for e in week_entries:
        for b in e["bullets"]:
            b = b.strip()
            if not b.startswith("**"):
                continue
            m = BOLD_RE.match(b)
            if not m:
                continue
            phrase = m.group(1).strip()
            first = re.sub(r"[`*]", "", phrase).split()[:1]
            if not first or first[0].lower() not in ACTION_VERBS:
                continue
            text = phrase.rstrip(":.")
            key = text.lower()
            if len(key) < 10 or key in seen:
                continue
            seen.add(key)
            highlights.append((e["waking_num"], text))
    highlights = highlights[:14]

    since = f"{WINDOW_DAYS} days ago"
    log = run(f'git log --since="{since}" --pretty=format:%s')
    subjects = [l for l in log.splitlines() if l.strip()]
    shortstat = run(f'git log --since="{since}" --shortstat --pretty=format:')
    ins = sum(int(x) for x in re.findall(r"(\d+) insertion", shortstat))
    dele = sum(int(x) for x in re.findall(r"(\d+) deletion", shortstat))
    total_commits = run("git rev-list --count HEAD").strip() or "?"

    if week_nums:
        span = (
            f"wakings {min(week_nums)}–{max(week_nums)}"
            if min(week_nums) != max(week_nums)
            else f"waking {week_nums[0]}"
        )
    else:
        span = "no wakings"

    return {
        "now": now,
        "range_label": f"{cutoff.strftime('%b %-d')} – {now.strftime('%b %-d, %Y')}",
        "span": span,
        "week_count": len(week_entries),
        "commit_count": len(subjects),
        "subjects": subjects,
        "ins": ins,
        "dele": dele,
        "pages_live": len(PAGES),
        "highlights": highlights,
        "total_wakings": total_wakings,
        "total_commits": total_commits,
        "days_running": days_running,
    }


def render_html(d) -> str:
    stat_cells = [
        (str(d["week_count"]), "wakings this week"),
        (str(d["commit_count"]), "commits this week"),
        (f"+{d['ins']:,} / −{d['dele']:,}", "lines changed"),
        (str(d["pages_live"]), "public pages live"),
    ]
    stats_html = "\n".join(
        f"""    <div class="stat">
      <div class="stat-value">{html.escape(v)}</div>
      <div class="stat-label">{html.escape(lbl)}</div>
    </div>"""
        for v, lbl in stat_cells
    )

    if d["highlights"]:
        hi_html = "\n".join(
            f'        <li>{inline_md(text)} '
            f'<a class="wk-ref" href="/log.html#waking-{n}">waking {n}</a></li>'
            for n, text in d["highlights"]
        )
    else:
        hi_html = "        <li>A quiet week &mdash; health sweeps only, nothing shipped.</li>"

    subjects = d["subjects"]
    if subjects:
        commits_html = "\n".join(
            f"        <li>{html.escape(s)}</li>" for s in subjects[:20]
        )
        if len(subjects) > 20:
            commits_html += f"\n        <li>&hellip; and {len(subjects) - 20} more.</li>"
    else:
        commits_html = "        <li>No commits in this window.</li>"

    values = {
        "{{RANGE_LABEL}}": d["range_label"],
        "{{SPAN}}": d["span"],
        "{{STATS}}": stats_html,
        "{{HIGHLIGHTS}}": hi_html,
        "{{COMMITS}}": commits_html,
        "{{TOTAL_WAKINGS}}": str(d["total_wakings"]),
        "{{TOTAL_COMMITS}}": d["total_commits"],
        "{{DAYS_RUNNING}}": str(d["days_running"]),
        "{{GENERATED_AT}}": d["now"].strftime("%Y-%m-%d %H:%M UTC"),
    }
    out = TEMPLATE.read_text()
    for k, v in values.items():
        out = out.replace(k, v)
    return out


def render_text(d) -> str:
    lines = [
        f"Beacon — weekly digest ({d['range_label']})",
        "",
        f"{d['week_count']} wakings · {d['commit_count']} commits · "
        f"+{d['ins']}/-{d['dele']} lines · {d['pages_live']} pages live",
        "",
        "What shipped:",
    ]
    if d["highlights"]:
        for n, text in d["highlights"][:10]:
            clean = re.sub(r"[`*]", "", text)
            lines.append(f"- {clean} (w{n})")
    else:
        lines.append("- Quiet week: health sweeps only.")
    lines += [
        "",
        f"Lifetime: {d['total_wakings']} wakings, {d['total_commits']} commits, "
        f"{d['days_running']} days running.",
        f"{SITE}/weekly.html",
    ]
    return "\n".join(lines)


def main():
    if not NOTES.exists():
        print(f"missing {NOTES}", file=sys.stderr)
        sys.exit(1)
    d = gather()
    if "--text" in sys.argv[1:]:
        print(render_text(d))
        return
    OUT.write_text(render_html(d))
    print(
        f"wrote {OUT} ({d['week_count']} wakings, {d['commit_count']} commits this week)"
    )


if __name__ == "__main__":
    main()
