#!/usr/bin/env python3
"""Print the operator's own messages from pi session transcripts, one session at a time.

Read-only. A retrospective reads these to find where the operator corrected, redirected, or
rejected agent work, which tool logs cannot show. Subagent transcripts are skipped: their
user message is the parent's brief, not the operator. Output quotes private transcript
content: do not redirect it into a public repo.
usage: session-messages.py [--since YYYY-MM-DD|7d] [--cwd-match TEXT]... [--max-chars N] [--json]

--cwd-match keeps sessions whose working directory (from the transcript header) contains the
text, case-insensitively; repeat it to keep any of several. Messages injected by the harness
(skill bodies, compaction summaries, wake notices) are kept, since they cannot be told apart
reliably; read them as context.

Sources:
  HWORKS_PI_SESSIONS   pi session transcripts, **/*.jsonl (default ~/.pi/agent/sessions)
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

SUBAGENT_PATH = re.compile(r"(/run-\d+/session\.jsonl$|_transcript\.jsonl$|/subagent-artifacts/)")


def parse_since(s):
    m = re.fullmatch(r"(\d+)d", s)
    if m:
        return datetime.now(timezone.utc) - timedelta(days=int(m.group(1)))
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def to_dt(v):
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def text_of(content):
    if isinstance(content, str):
        return content
    parts = [c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text"]
    return "\n".join(p for p in parts if p)


def read(path, since, match):
    """Return (cwd, [(timestamp, text)]) for one transcript, or None when it is out of scope."""
    cwd, msgs = None, []
    try:
        f = open(path, errors="replace")
    except OSError:
        return None
    with f:
        for n, line in enumerate(f):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            if n == 0 and e.get("type") == "session":
                cwd = e.get("cwd") if isinstance(e.get("cwd"), str) else None
                if match and not any(m in (cwd or "").lower() for m in match):
                    return None
                continue
            m = e.get("message")
            if not isinstance(m, dict) or m.get("role") != "user":
                continue
            dt = to_dt(e.get("timestamp") or m.get("timestamp"))
            text = text_of(m.get("content")).strip()
            if dt and dt >= since and text:
                msgs.append((dt, text))
    if match and cwd is None:
        return None
    return cwd, msgs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 usage=argparse.SUPPRESS)
    ap.add_argument("--since", default="14d", help="YYYY-MM-DD or Nd (default 14d)")
    ap.add_argument("--cwd-match", action="append", default=[], metavar="TEXT",
                    help="keep sessions whose cwd contains TEXT (repeatable)")
    ap.add_argument("--max-chars", type=int, default=600, help="truncate each message (default 600, 0 for none)")
    ap.add_argument("--json", action="store_true", help="one JSON object per message")
    args = ap.parse_args(argv)
    since = parse_since(args.since)
    match = [m.lower() for m in args.cwd_match]
    root = os.environ.get("HWORKS_PI_SESSIONS") or os.path.expanduser("~/.pi/agent/sessions")
    if not os.path.isdir(root):
        print(f"note: pi sessions: not found ({root})", file=sys.stderr)
        return
    cutoff = since.timestamp()
    sessions = []
    for p in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        rel = os.path.relpath(p, root)
        if SUBAGENT_PATH.search("/" + rel):
            continue
        try:
            if os.path.getmtime(p) < cutoff:
                continue
        except OSError:
            continue
        got = read(p, since, match)
        if got and got[1]:
            sessions.append((got[1][0][0], rel, got[0], got[1]))
    sessions.sort()
    for _, rel, cwd, msgs in sessions:
        if not args.json:
            print(f"== {rel}\n   cwd: {cwd}")
        for dt, text in msgs:
            if args.max_chars and len(text) > args.max_chars:
                text = text[:args.max_chars] + " [...]"
            if args.json:
                print(json.dumps({"session": rel, "cwd": cwd, "ts": dt.isoformat(timespec="seconds"), "text": text}))
            else:
                print(f"   {dt.isoformat(timespec='minutes')}  " + text.replace("\n", "\n" + " " * 21))
        if not args.json:
            print()


if __name__ == "__main__":
    main()
