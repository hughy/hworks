#!/usr/bin/env python3
"""Prepare a kaizen run: the window, the scaled triage thresholds, the reporter commands, and the
previous findings still to reconcile.

usage: kaizen-prep.py [--since YYYY-MM-DD|Nd] [--task-dir DIR] [--previous FILE] [--no-gh] [--json]

Window: --since as the other kaizen reporters take it (default 14d), printed in days.
Sources: whether the sessions dir and tasks dir (as kaizen-sessions.py resolves them) and
HWORKS_HARNESS_AUDIT_LOG (when set) exist; for the sessions dir, the *.jsonl files modified in
the window, main and child, with the oldest and newest modification dates. Then each host in
`gh auth status` (binary from HWORKS_GH, timeout GH_TIMEOUT seconds) as logged in, failed with
its reason, or gh as not configured. --no-gh skips the gh check. adapters/local/*.env is read
first; values already in the environment win.
Thresholds: group 5, blocker class / mistake / guidance gap 3, new tool 10, each set for 14 days,
scaled by days/14, rounded up, never below 3.
Commands: the five reporters from skills/kaizen/SKILL.md with --since and --min-sessions filled
in, output files dated today.
Carry-over: --previous FILE, else the newest findings-*.md in --task-dir (default: the output of
scripts/task-dir.sh kaizen run from the hworks root). Every line starting with "- [" is a finding
in the skill's Output format (six "|"-separated fields, or two for a drop, none empty; the state
may carry a note after the state word, as in `implemented (merged, effect not yet seen)`); one that
does not parse is listed, never skipped. Findings with an
id whose state is not `effective` are listed by state; drops and `effective` rows are counted.
--previous naming a missing file exits 2.
"""
import argparse
import glob
import importlib.util
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("kaizen_sessions", os.path.join(HERE, "kaizen-sessions.py"))
ks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ks)
_spec = importlib.util.spec_from_file_location("kaizen_tokens", os.path.join(HERE, "kaizen-tokens.py"))
kt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kt)

BASES = {"group": 5, "blocker_mistake_guidance": 3, "new_tool": 10}
OUTCOMES = {"1", "2", "3", "4", "5", "investigate", "drop"}
GH_TIMEOUT = 20
STATES = ["open", "awaiting-user", "implemented", "effective", "unproven", "pending"]


def window_days(since):
    return (datetime.now(timezone.utc).date() - ks.parse_since(since).date()).days


def thresholds(days):
    return {k: max(3, -(-b * days // 14)) for k, b in BASES.items()}


def commands(since, group, today):
    s = os.path.join(ROOT, "scripts")
    return [
        f'python3 {s}/kaizen-sessions.py --since {since} --min-sessions {group} --top 1000 > "$TASK_DIR/sessions-{today}.txt"',
        f'python3 {s}/kaizen-tokens.py --since {since} --min-sessions {group} --top 40 > "$TASK_DIR/tokens-{today}.txt"',
        f'python3 {s}/kaizen-prs.py --since {since} --top 40 > "$TASK_DIR/prs-{today}.txt"',
        f'{s}/blockers.sh --since {since} > "$TASK_DIR/blockers-{today}.txt"',
        f'python3 {s}/kaizen-setup.py --since {since} > "$TASK_DIR/setup-{today}.txt"',
    ]


def session_files(root, since):
    """Counts of *.jsonl modified since, main and child, and the oldest and newest dates."""
    cutoff, counts, mtimes = since.timestamp(), {"main": 0, "child": 0}, []
    for p in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        if "/subagent-artifacts/" in p:
            continue
        try:
            t = os.path.getmtime(p)
        except OSError:
            continue
        if t >= cutoff:
            counts["child" if kt.CHILD.search(p) else "main"] += 1
            mtimes.append(t)
    day = lambda t: datetime.fromtimestamp(t, timezone.utc).date().isoformat()
    return {**counts, "oldest": day(min(mtimes)) if mtimes else None, "newest": day(max(mtimes)) if mtimes else None}


def parse_gh_auth(text):
    """{host: "logged in" | "failed: <reason>"} from `gh auth status` output."""
    hosts, host, failed = {}, None, False
    for line in text.splitlines():
        if line.strip() and not line[0].isspace():
            host, failed = line.strip(), False
            continue
        t = line.strip()
        if host is None or not t:
            continue
        if t.startswith("\u2713"):
            hosts.setdefault(host, "logged in")
        elif t.startswith("X "):
            failed = True
            hosts[host] = f"failed: {t[2:]}"
        elif failed and t.startswith("- ") and not t.startswith(("- Active account", "- Git operations", "- Token")):
            hosts[host] = f"failed: {t[2:]}"
            failed = False
    return hosts


def gh_hosts():
    gh = os.environ.get("HWORKS_GH") or "gh"
    try:
        p = subprocess.run([gh, "auth", "status"], capture_output=True, text=True, timeout=GH_TIMEOUT)
    except FileNotFoundError:
        return {}, f"{gh}: not found"
    except subprocess.TimeoutExpired:
        return {}, f"{gh} auth status: timed out after {GH_TIMEOUT}s"
    out = p.stdout + p.stderr
    hosts = parse_gh_auth(out)
    first = next((x.strip() for x in out.splitlines() if x.strip()), f"exit {p.returncode}")
    return hosts, None if hosts else first


def source_report(since, check_gh):
    src = ks.sources()
    rows = [{"name": "sessions", "path": src["sessions"], "exists": os.path.isdir(src["sessions"])},
            {"name": "tasks", "path": src["tasks"], "exists": os.path.isdir(src["tasks"])}]
    if rows[0]["exists"]:
        rows[0]["files"] = session_files(src["sessions"], since)
    audit = os.environ.get("HWORKS_HARNESS_AUDIT_LOG")
    if audit:
        rows.append({"name": "harness audit log", "path": audit, "exists": os.path.exists(audit)})
    gh = {"checked": False}
    if check_gh:
        hosts, why = gh_hosts()
        gh = {"checked": True, "hosts": hosts, "not_configured": why}
    return {"paths": rows, "gh": gh}


def print_sources(s):
    print("Sources:")
    for r in s["paths"]:
        state = "found" if r["exists"] else "MISSING"
        print(f"  {r['name']}: {state} ({r['path']})")
        f = r.get("files")
        if f:
            print(f"    jsonl modified in window: {f['main']} main, {f['child']} child; "
                  f"oldest {f['oldest'] or '-'}, newest {f['newest'] or '-'}")
    gh = s["gh"]
    if not gh["checked"]:
        print("  gh: not checked (--no-gh)")
    elif gh["not_configured"]:
        print(f"  gh: not configured ({gh['not_configured']})")
    for host, state in (gh.get("hosts") or {}).items():
        print(f"  gh {host}: {state}")
    if any(v.startswith("failed") for v in (gh.get("hosts") or {}).values()):
        print("  PRs on a failed host will not fetch: name it at the top of the findings file.")
    print()


def parse_line(line):
    """Return a finding dict for one '- [' line, or None when it does not match the Output format."""
    body = line.strip()[2:].lstrip()
    if not body.startswith("[") or "]" not in body:
        return None
    outcome, rest = body[1:].split("]", 1)
    outcome = outcome.strip()
    if outcome not in OUTCOMES:
        return None
    fields = [f.strip() for f in rest.split("|")]
    # An extra "|" inside a field would shift every later field, so an exact count is required.
    if len(fields) != (2 if outcome == "drop" else 6) or not all(fields):
        return None
    if outcome == "drop":
        return {"outcome": "drop", "group": fields[0]}
    head = fields[0].split(None, 1)
    state = fields[5].split(None, 1)[0]
    if len(head) < 2 or state not in STATES:
        return None
    return {"outcome": outcome, "id": head[0], "group": head[1], "deliverable": fields[3],
            "artifact": fields[4], "state": state}


def carry_over(path):
    by_state, unparsed, drops, effective = {}, [], 0, 0
    with open(path) as f:
        for n, line in enumerate(f, 1):
            if not line.lstrip().startswith("- ["):
                continue
            r = parse_line(line)
            if r is None:
                unparsed.append({"line": n, "text": line.rstrip("\n")})
            elif r["outcome"] == "drop":
                drops += 1
            elif r["state"] == "effective":
                effective += 1
            else:
                by_state.setdefault(r.pop("state"), []).append(r)
    carried = sum(len(v) for v in by_state.values())
    return by_state, unparsed, {"carry_over": carried, "drop": drops, "effective": effective,
                                "unparsed": len(unparsed)}


def default_task_dir():
    try:
        out = subprocess.run([os.path.join(ROOT, "scripts", "task-dir.sh"), "kaizen"], cwd=ROOT,
                             capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        return None, f"task-dir.sh kaizen failed ({e}); carry-over skipped"
    return out.stdout.strip(), None


def find_previous(task_dir):
    files = sorted(glob.glob(os.path.join(task_dir, "findings-*.md")))
    return files[-1] if files else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 usage=argparse.SUPPRESS)
    ap.add_argument("--since", default="14d", help="YYYY-MM-DD or Nd (default 14d)")
    ap.add_argument("--task-dir", help="kaizen task dir to search for findings-*.md")
    ap.add_argument("--previous", help="previous findings file to reconcile")
    ap.add_argument("--no-gh", action="store_true", help="skip the gh auth check")
    ap.add_argument("--json", action="store_true", help="one JSON object")
    args = ap.parse_args(argv)
    ks.load_env_files(ROOT)
    try:
        days = window_days(args.since)
    except ValueError:
        ap.error(f"--since: expected YYYY-MM-DD or Nd, got {args.since!r}")
    if days < 0:
        ap.error(f"--since {args.since} is in the future")
    th = thresholds(days)
    today = date.today().isoformat()
    cmds = commands(args.since, th["group"], today)

    note, prev = None, args.previous
    if prev:
        if not os.path.isfile(prev):
            print(f"kaizen-prep.py: --previous {prev}: no such file", file=sys.stderr)
            return 2
    else:
        task_dir = args.task_dir
        if task_dir is None:
            task_dir, note = default_task_dir()
        if task_dir:
            prev = find_previous(task_dir)
            if prev is None:
                note = f"no findings-*.md in {task_dir}"
    by_state, unparsed, counts = carry_over(prev) if prev else ({}, [], None)
    srcs = source_report(ks.parse_since(args.since), not args.no_gh)

    if args.json:
        print(json.dumps({"window_days": days, "sources": srcs, "thresholds": th, "commands": cmds, "previous_file": prev,
                          "note": note, "carry_over": by_state, "unparsed": unparsed, "counts": counts},
                         indent=2))
        return 0
    print(f"Window: {days} days (--since {args.since})")
    print_sources(srcs)
    print("Thresholds (sessions, scaled from 14 days):")
    print(f"  group {th['group']}")
    print(f"  blocker class / mistake / guidance gap {th['blocker_mistake_guidance']}")
    print(f"  new tool {th['new_tool']}")
    print(f"\nReporters (output files dated today, {today}):")
    for c in cmds:
        print(f"  {c}")
    print()
    if not prev:
        print(f"Previous findings: none ({note})")
        return 0
    print(f"Previous findings: {prev}")
    print(f"  {counts['carry_over']} to reconcile, {counts['drop']} dropped, {counts['effective']} effective, "
          f"{counts['unparsed']} could not parse")
    for state in STATES:
        rows = by_state.get(state, [])
        if rows:
            print(f"\n== {state} ==")
        for r in rows:
            print(f"  {r['id']} [{r['outcome']}] {r['group']}")
            print(f"      deliverable: {r['deliverable']}")
            print(f"      artifact: {r['artifact']}")
    if unparsed:
        print("\n== could not parse ==")
        for u in unparsed:
            print(f"  line {u['line']}: {u['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
