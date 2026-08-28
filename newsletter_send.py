#!/usr/bin/env python3
"""Push a weekly newsletter draft to Buttondown as a DRAFT email.

Reads a Markdown draft (default: the newest shared/outbox/weekly-newsletter-*.md),
strips the internal review preamble above the first horizontal rule, takes the
first `## ` heading in the body as the subject, and POSTs the rest to Buttondown's
/v1/emails endpoint.

By design this creates a *draft* only. Sending a real email to real subscribers
is a human-gated action (AGENT.md): josh opens the draft in the Buttondown
dashboard, reads it, and hits send. `--send` exists for an attended run but is
never used by an unattended waking.

Needs keys/buttondown.env (gitignored) with:
    BUTTONDOWN_API_KEY=...

Usage:
    python3 newsletter_send.py [draft.md] [--subject "..."] [--send] [--dry-run]
"""
import glob
import json
import os
import sys
import urllib.error
import urllib.request

API_BASE = "https://api.buttondown.com/v1"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(SCRIPT_DIR, "keys", "buttondown.env")
OUTBOX_GLOB = "/home/agent/shared/outbox/weekly-newsletter-*.md"


def load_api_key():
    if not os.path.isfile(ENV_FILE):
        sys.exit(f"Missing {ENV_FILE} (need BUTTONDOWN_API_KEY=...)")
    key = None
    with open(ENV_FILE) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("BUTTONDOWN_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key or key.startswith("REPLACE_ME"):
        sys.exit(f"BUTTONDOWN_API_KEY not set in {ENV_FILE}")
    return key


def pick_draft(argv):
    for a in argv:
        if not a.startswith("-") and a.endswith(".md"):
            return a
    matches = sorted(glob.glob(OUTBOX_GLOB))
    if not matches:
        sys.exit(f"No draft given and nothing matches {OUTBOX_GLOB}")
    return matches[-1]


def split_draft(text):
    """Return (body_markdown, first_h2_or_None).

    The draft files carry a review preamble (metadata, voice notes, Beacon's
    sign-off) above a `---` rule. Everything from the *last* preamble rule
    onward is the newsletter itself.
    """
    marker = "\n---\n"
    idx = text.find(marker)
    body = text[idx + len(marker):] if idx != -1 else text
    body = body.strip()
    subject = None
    for line in body.splitlines():
        if line.startswith("## "):
            subject = line[3:].strip()
            break
    return body, subject


def main():
    argv = sys.argv[1:]
    dry_run = "--dry-run" in argv
    send = "--send" in argv
    subject = None
    if "--subject" in argv:
        i = argv.index("--subject")
        subject = argv[i + 1]

    draft_path = pick_draft(argv)
    with open(draft_path) as fh:
        raw = fh.read()
    body, auto_subject = split_draft(raw)
    subject = subject or auto_subject
    if not subject:
        sys.exit("Could not derive a subject; pass --subject \"...\"")

    status = "about_to_send" if send else "draft"
    payload = {"subject": subject, "body": body, "status": status}

    print(f"draft:   {draft_path}")
    print(f"subject: {subject}")
    print(f"status:  {status}  ({'SENDS to list' if send else 'draft only'})")
    print(f"body:    {len(body)} chars")
    if dry_run:
        print("\n--dry-run: not posting.")
        return

    if send:
        reply = input('Type "send" to push as about_to_send: ').strip()
        if reply != "send":
            sys.exit("aborted")

    req = urllib.request.Request(
        f"{API_BASE}/emails",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Token {load_api_key()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"Buttondown API {e.code}: {e.read().decode(errors='replace')}")

    eid = data.get("id", "?")
    print(f"\nOK — email {eid} created as {data.get('status', status)}.")
    print("Review / send it in the Buttondown dashboard: https://buttondown.com/emails")


if __name__ == "__main__":
    main()
