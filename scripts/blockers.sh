#!/usr/bin/env bash
# Report where agent runs blocked: guard blocks, asks, supervisor decision requests,
# idle or failed subagents, harness confirm prompts, deferred and asked open questions with
# how the operator judged them (kept or reversed), and friction (work the operator, a reviewer,
# a test, or CI caught and sent back).
# Read-only. Feed the output to /skill:correct to fix recurring classes.
# usage: blockers.sh [--since YYYY-MM-DD|7d] [--cwd-match TEXT]... [--source S] [--kind K] [--json]
#   --cwd-match keeps events whose cwd or task path contains TEXT, case-insensitively.
#   --source and --kind keep events with that exact source or kind (e.g. --source friction --kind operator).
#
# Sources (each optional; a missing one is reported, not fatal):
#   HWORKS_BLOCKERS_LOG        autonomy.ts log (default $HWORKS_TASKS_DIR/blockers.jsonl)
#   HWORKS_TASKS_DIR           open-questions.md and friction.md files (default $XDG_STATE_HOME/agent-tasks;
#                              $XDG_STATE_HOME defaults to ~/.local/state)
#   HWORKS_SUBAGENT_RUNS       pi-subagents async run dirs (default $TMPDIR/pi-subagents-uid-$UID/async-subagent-runs)
#   HWORKS_RUN_HISTORY         pi-subagents run history (default ~/.pi/agent/run-history.jsonl)
#   HWORKS_HARNESS_AUDIT_LOG   a harness guard audit log: JSONL rows with ts, action, rule (unset by default)
# adapters/local/blockers.env, when present, is sourced first to set any of these.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck disable=SC1091
[ -f "$root/adapters/local/blockers.env" ] && . "$root/adapters/local/blockers.env"

since=7d; json=0; match=; source=; kind=
while [ $# -gt 0 ]; do
  case "$1" in
    --since) since=${2:?--since needs a value}; shift 2 ;;
    --json) json=1; shift ;;
    --cwd-match) match="$match${match:+$'\n'}${2:?--cwd-match needs a value}"; shift 2 ;;
    --source) source=${2:?--source needs a value}; shift 2 ;;
    --kind) kind=${2:?--kind needs a value}; shift 2 ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

export BLOCKERS_SINCE=$since BLOCKERS_JSON=$json BLOCKERS_MATCH=$match BLOCKERS_SOURCE=$source BLOCKERS_KIND=$kind
export HWORKS_TASKS_DIR=${HWORKS_TASKS_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/agent-tasks}
export HWORKS_BLOCKERS_LOG=${HWORKS_BLOCKERS_LOG:-$HWORKS_TASKS_DIR/blockers.jsonl}
export HWORKS_SUBAGENT_RUNS=${HWORKS_SUBAGENT_RUNS:-${TMPDIR:-/tmp}/pi-subagents-uid-$(id -u)/async-subagent-runs}
export HWORKS_RUN_HISTORY=${HWORKS_RUN_HISTORY:-$HOME/.pi/agent/run-history.jsonl}
export HWORKS_HARNESS_AUDIT_LOG=${HWORKS_HARNESS_AUDIT_LOG:-}

exec python3 - <<'PY'
import glob, json, os, re, sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

def parse_since(s):
    m = re.fullmatch(r"(\d+)d", s)
    if m:
        return datetime.now(timezone.utc) - timedelta(days=int(m.group(1)))
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def to_dt(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def jsonl(path):
    try:
        with open(path, errors="replace") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return

since = parse_since(os.environ["BLOCKERS_SINCE"])
match = [m.lower() for m in os.environ["BLOCKERS_MATCH"].split("\n") if m]
only_source, only_kind = os.environ["BLOCKERS_SOURCE"], os.environ["BLOCKERS_KIND"]
rows, notes = [], []

def add(source, kind, rule, ts, session=None, cwd=None, detail="", verdict=None):
    dt = to_dt(ts)
    if dt is None or dt < since:
        return
    if match and not any(m in f"{cwd or ''} {session or ''}".lower() for m in match):
        return
    if (only_source and source != only_source) or (only_kind and kind != only_kind):
        return
    rows.append({"ts": dt.isoformat(timespec="seconds"), "source": source, "kind": kind, "rule": rule,
                 "session": session, "cwd": cwd, "detail": re.sub(r"\s+", " ", str(detail or ""))[:200],
                 "verdict": verdict})

def need(path, label):
    if path and os.path.exists(path):
        return True
    notes.append(f"{label}: not found ({path or 'unset'})")
    return False

p = os.environ["HWORKS_BLOCKERS_LOG"]
if need(p, "autonomy log"):
    for o in jsonl(p):
        add("autonomy", o.get("kind"), o.get("rule"), o.get("ts"), o.get("session"), o.get("cwd"), o.get("detail"))

d = os.environ["HWORKS_TASKS_DIR"]
entry = re.compile(r"^\s*-\s*\[([a-z-]+)\]\s*(.*)$")
# The last field is the state: deferred or asked, then :kept or :reversed once the operator judged it.
# Lines written before the state field existed are "unrecorded" and stay out of the rates.
state = re.compile(r"^(deferred|asked)(?::(kept|reversed))?$")
if need(d, "open questions"):
    for f in glob.glob(os.path.join(d, "**", "open-questions.md"), recursive=True):
        mtime = os.path.getmtime(f)
        task = os.path.relpath(os.path.dirname(f), d)
        for line in open(f, errors="replace"):
            m = entry.match(line)
            if m:
                fields = [x.strip() for x in m.group(2).split("|")]
                sm = state.match(fields[-1].lower()) if len(fields) >= 5 else None
                stage, verdict = (sm.group(1), sm.group(2) or "open") if sm else ("unrecorded", None)
                add("open-questions", stage, m.group(1), mtime, None, task, m.group(2), verdict)
            elif line.lstrip().startswith("- "):
                add("open-questions", "unrecorded", "uncategorized", mtime, None, task, line.strip()[2:])

friction = re.compile(r"^\s*-\s*(?:(\d{4}-\d{2}-\d{2})\s+)?\[([a-z0-9-]+)\]\s*(.*)$")
if os.path.isdir(d):
    for f in glob.glob(os.path.join(d, "**", "friction.md"), recursive=True):
        mtime = os.path.getmtime(f)
        task = os.path.relpath(os.path.dirname(f), d)
        for line in open(f, errors="replace"):
            m = friction.match(line)
            if m:
                fields = [x.strip() for x in m.group(3).split("|")]
                caught = fields[1].lower() if len(fields) > 1 and fields[1] else "unknown"
                add("friction", caught, m.group(2), m.group(1) or mtime, None, task, m.group(3))

d = os.environ["HWORKS_SUBAGENT_RUNS"]
if need(d, "subagent runs"):
    for run in glob.glob(os.path.join(d, "*")):
        for o in jsonl(os.path.join(run, "events.jsonl")):
            ev = o.get("event") if o.get("type") == "subagent.control" else None
            if isinstance(ev, dict) and ev.get("type") == "needs_attention":
                add("subagents", "needs_attention", ev.get("reason") or "unknown", ev.get("ts"),
                    os.path.basename(run), None, f"{ev.get('agent')}: {ev.get('message')}")
        try:
            st = json.load(open(os.path.join(run, "status.json")))
        except (OSError, ValueError):
            continue
        if st.get("state") in ("failed", "paused"):
            add("subagents", st["state"], st.get("error") or st.get("pauseReason") or "-",
                st.get("lastUpdate") or st.get("startedAt"), os.path.basename(run), st.get("cwd"))

p = os.environ["HWORKS_RUN_HISTORY"]
if need(p, "run history"):
    for o in jsonl(p):
        if o.get("status") != "ok":
            add("run-history", o.get("outcome") or o.get("status"), o.get("agent"), o.get("ts"),
                None, None, f"duration {o.get('duration')}")

p = os.environ["HWORKS_HARNESS_AUDIT_LOG"]
if need(p, "harness audit log"):
    for o in jsonl(p):
        if o.get("action") in ("prompted", "blocked", "timeout"):
            add("harness", o["action"], o.get("rule") or o.get("kind"), o.get("ts"), o.get("sid"), o.get("cwd"),
                o.get("cmd") or o.get("filePath") or o.get("reason"))

rows.sort(key=lambda r: r["ts"])
if os.environ["BLOCKERS_JSON"] == "1":
    for r in rows:
        print(json.dumps(r))
    sys.exit(0)

groups = defaultdict(list)
for r in rows:
    groups[(r["source"], r["kind"], r["rule"])].append(r)

print(f"Blockers since {since.date()} ({len(rows)} events)\n")
if groups:
    print(f"{'count':>5} {'sess':>4}  source / kind / rule")
for key, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    sessions = {r["session"] or r["cwd"] for r in rs}
    print(f"{len(rs):>5} {len(sessions):>4}  {' / '.join(str(k) for k in key)}")
    for r in rs[-3:]:
        where = r["cwd"] or r["session"] or ""
        print(f"            {r['ts'][:16]}  {where[-40:]}  {r['detail'][:90]}")
by_branch = defaultdict(int)
for r in rows:
    if r["source"] == "open-questions":
        parts = (r["cwd"] or "").split("/")
        by_branch["/".join(parts[:2]) if len(parts) >= 3 and "--" in parts[0] else f"(legacy) {parts[0]}"] += 1
if by_branch:
    print("\nOpen-question entries by repo/branch")
    for k, n in sorted(by_branch.items(), key=lambda kv: -kv[1]):
        print(f"{n:>5}  {k}")
outcomes = defaultdict(lambda: {"open": 0, "kept": 0, "reversed": 0})
for r in rows:
    if r["source"] == "open-questions" and r["verdict"]:
        for key in ((r["kind"], r["rule"]), (r["kind"], "(all)")):
            outcomes[key][r["verdict"]] += 1
if outcomes:
    print("\nDecision outcomes (reversed share of judged entries; deferred = the agent decided, asked = up-front round)")
    print(f"{'stage':<9} {'category':<16} {'open':>5} {'kept':>5} {'rev':>5}  reversed")
    for (stage, cat), c in sorted(outcomes.items(), key=lambda kv: (kv[0][0], kv[0][1] != "(all)", kv[0][1])):
        judged = c["kept"] + c["reversed"]
        share = f"{c['reversed']}/{judged} ({c['reversed'] / judged:.0%})" if judged else "-"
        print(f"{stage:<9} {cat:<16} {c['open']:>5} {c['kept']:>5} {c['reversed']:>5}  {share}")
unrecorded = sum(1 for r in rows if r["source"] == "open-questions" and not r["verdict"])
if unrecorded:
    print(f"\n{unrecorded} open-question entries have no state field (written before it existed or malformed)")
for n in notes:
    print(f"\nnote: {n}", file=sys.stderr)
PY
