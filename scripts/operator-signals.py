#!/usr/bin/env python3
"""Find patterns in how the operator works with agents, from the operator's own pi messages.

Read-only. Reads only sessions the operator started (subagent transcripts are skipped) and,
in them, the messages the operator typed, with harness injections removed. Reports signals
ranked by distinct sessions, each with counts and examples that quote the operator's message
and the end of the agent's last text before it (with --context, also the start of the agent's
next text after it). Output goes to stdout and quotes private prompts and
transcript content: do not redirect it into a repo.
usage: operator-signals.py [--since YYYY-MM-DD|Nd] [--cwd-match TEXT]... [--min-sessions N]
                           [--examples N] [--max-chars N] [--context] [--json]

Sources (each optional; a missing one is reported, not fatal):
  HWORKS_PI_SESSIONS      pi session transcripts, **/*.jsonl (default ~/.pi/agent/sessions)
  HWORKS_OPERATOR_SKIP    regex; a user message whose raw text matches it (re.search) is not
                          operator-authored, for example an automation ping, and is dropped
  HWORKS_INJECTED_PREFIX  regex for more leading injected text to strip (re.match, repeated)
adapters/local/*.env, when present, is read first to set any of these; values already in the
environment win.

Scope: a transcript under /subagent-artifacts/, named *_transcript.jsonl, or at
run-<N>/session.jsonl is a subagent's and is skipped. --since drops messages before it, and a
session with no user message after it counts as out of window. --cwd-match keeps sessions
whose recorded cwd contains any of the given strings. Operator text is a user message's text
after leading injections are removed: a <skill name="X" ...>...</skill> block (an invocation
of skill X, counted under skills), any other leading <tag ...>...</tag> block, and
HWORKS_INJECTED_PREFIX matches. A message left with no text and no skill invocation is not an
operator message; a session with no operator message is skipped.

Signals (groups below --min-sessions are hidden, except skills and prompt-shape):
  approval      a bare consent of at most APPROVAL_MAX_WORDS words (yes, ok, go ahead, lgtm,
                ...) right after an assistant turn that ended (stopReason "stop"): the agent
                stopped to ask permission. Grouped by the normalized phrase.
  status-check  a message of at most STATUS_MAX_WORDS words that, normalized, is wholly a
                progress query (status?, any update, checking progress, how's it going, ...),
                so "show git status" or "add a progress bar" is not one. Grouped by phrase.
  correction    a message whose opening matches a correction cue (no, actually, wrong, I
                meant, revert, ...), grouped by cue. A bare "no" counts only alone, before
                punctuation, or before a word in NO_FOLLOWERS, so "no tests fail" is not one.
                A lead: it can mean an unclear prompt or a bad agent turn.
  abort         an operator message right after an assistant message with stopReason
                "aborted": the operator interrupted a turn to redirect.
  repeat        operator messages of at least REPEAT_MIN_CHARS characters whose word
                3-shingle sets have Jaccard similarity at least REPEAT_THRESHOLD, grouped
                transitively; a group must span at least two sessions. Identical shingle sets
                merge before clustering, so a prompt repeated hundreds of times still groups.
  skills        invocations per skill (sessions and count), and sessions with none.
  prompt-shape  sessions bucketed by the word count of their first operator message
                (terse 0-10, short 11-40, medium 41-150, long 151+), with median operator
                messages per session and the share of sessions with a correction or approval.
Counts are heuristic: compare them to each other, not to a target.
"""
import argparse
import bisect
import glob
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APPROVAL_MAX_WORDS = 4
STATUS_MAX_WORDS = 8
REPEAT_MIN_CHARS = 80
REPEAT_THRESHOLD = 0.5
SHINGLE = 3
BUCKETS = [("terse", 0, 10), ("short", 11, 40), ("medium", 41, 150), ("long", 151, None)]

SUBAGENT = re.compile(r"(/run-\d+/session\.jsonl$|_transcript\.jsonl$|/subagent-artifacts/)")
SKILL_BLOCK = re.compile(r'<skill\s+name="([^"]+)"[^>]*>.*?</skill>', re.S)
TAG_BLOCK = re.compile(r"<([A-Za-z][\w.-]*)(?:\s[^>]*)?>.*?</\1>", re.S)

APPROVAL = re.compile(
    r"(?:y|ya|yes|yep|yeah|yup|sure|ok|okay|k|go|go ahead|go for it|proceed|continue|resume|keep going|carry on|"
    r"lgtm|do it|ship it|sounds good|looks good|commit|commit it|approved|confirm|confirmed|please do|"
    r"yes please|ok go|ok proceed|yes proceed|yes go ahead|yes do it|ok do it|go on)(?: please| thanks)?")
STATUS = re.compile(
    r"(?:(?:hey|so|ok|okay|and|quick)\s+)?"
    r"(?:(?:(?:what's|whats|what is) the |any |a )?(?:status|progress|update|updates|eta)"
    r"(?: (?:update|check|report|so far|now|please))*"
    r"|how(?:'s| is) it going|how(?:'s| is) it looking|where are (?:we|you|things)(?: at)?(?: now)?"
    r"|how far along(?: are you)?|are you done(?: yet)?|done yet|still (?:working|running)"
    r"|what's happening|whats happening|checking (?:in|progress|status)|check(?:ing)? on progress)")
CORRECTION = re.compile(
    r"(nope|not that|actually|wrong|that's not|thats not|that is not|stop|don't|dont|do not|instead|"
    r"i said|i meant|why did you|revert|undo)\b")
NO_FOLLOWERS = {"not", "that", "this", "the", "you", "i", "we", "it", "don't", "dont", "do", "wait", "stop",
                "please", "thats", "that's", "use", "keep", "leave"}


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


def load_env_files(root=ROOT):
    for path in sorted(glob.glob(os.path.join(root, "adapters", "local", "*.env"))):
        try:
            lines = open(path, errors="replace").read().splitlines()
        except OSError:
            continue
        for line in lines:
            m = re.match(r"\s*(?:export\s+)?([A-Za-z_]\w*)=(.*)$", line)
            if not m:
                continue
            val = m.group(2).strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
                val = val[1:-1]
            os.environ.setdefault(m.group(1), os.path.expanduser(os.path.expandvars(val)))


def sources():
    def rx(name):
        v = os.environ.get(name)
        return re.compile(v, re.S) if v else None
    return {
        "sessions": os.environ.get("HWORKS_PI_SESSIONS") or os.path.expanduser("~/.pi/agent/sessions"),
        "skip": rx("HWORKS_OPERATOR_SKIP"),
        "prefix": rx("HWORKS_INJECTED_PREFIX"),
    }


def short(text, n):
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= n else t[:max(n - 3, 0)] + "..."


def tail(text, n):
    """The last n characters: an agent turn ends with its question or offer."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if len(t) <= n:
        return t
    return "..." + t[len(t) - max(n - 3, 0):]


def content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text") or "" for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def strip_injections(text, prefix=None):
    """(operator text, skills invoked) after removing leading harness injections."""
    skills = []
    while True:
        t = text.lstrip()
        m = SKILL_BLOCK.match(t)
        if m:
            skills.append(m.group(1))
        else:
            m = TAG_BLOCK.match(t)
            if not m and prefix:
                m = prefix.match(t)
                if m and not m.group(0):
                    m = None
        if not m:
            return t.strip(), skills
        text = t[m.end():]


def read_session(path, since, src, notes):
    """(cwd, user messages after since, operator messages after since). Each operator message
    carries its text, skills, timestamp, the preceding assistant's text and stopReason, and the
    next assistant text after it."""
    cwd, users, ops, bad = None, 0, [], 0
    waiting = []
    last_text, last_stop = "", None
    try:
        f = open(path, errors="replace")
    except OSError as e:
        notes.append(f"{path}: {e}")
        return cwd, users, ops
    with f:
        for n, line in enumerate(f):
            try:
                e = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(e, dict):
                continue
            if n == 0 and e.get("type") == "session":
                cwd = e.get("cwd") if isinstance(e.get("cwd"), str) else None
                continue
            m = e.get("message")
            if e.get("type") != "message" or not isinstance(m, dict):
                continue
            role = m.get("role")
            if role == "assistant":
                t = content_text(m.get("content")).strip()
                if t:
                    last_text = t
                    for op in waiting:
                        op["after"] = t
                    waiting = []
                last_stop = m.get("stopReason")
            elif role == "user":
                prev_stop, last_stop = last_stop, None
                dt = to_dt(e.get("timestamp") or m.get("timestamp"))
                if dt is None or dt < since:
                    continue
                users += 1
                raw = content_text(m.get("content"))
                if src["skip"] and src["skip"].search(raw):
                    continue
                text, skills = strip_injections(raw, src["prefix"])
                if not text and not skills:
                    continue
                ops.append({"text": text, "skills": skills, "ts": dt.isoformat().replace("+00:00", "Z"),
                            "agent": last_text, "prev_stop": prev_stop, "after": ""})
                waiting.append(ops[-1])
    if bad:
        notes.append(f"{path}: skipped {bad} malformed line(s)")
    return cwd, users, ops


def norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", text.lower().replace("\u2019", "'"))).strip()


def approval(op):
    t = norm(op["text"])
    return t if op["prev_stop"] == "stop" and t and len(t.split()) <= APPROVAL_MAX_WORDS and APPROVAL.fullmatch(t) else None


def status_check(op):
    t = norm(op["text"])
    return t if t and len(t.split()) <= STATUS_MAX_WORDS and STATUS.fullmatch(t) else None


def correction(op):
    t = op["text"].lower().replace("\u2019", "'").lstrip(" \t\n\"'*_-")
    m = CORRECTION.match(t)
    if m:
        return m.group(1).replace("dont", "don't").replace("thats", "that's")
    m = re.match(r"no(?![\w'])\s*(.*)", t, re.S)
    if not m:
        return None
    rest = m.group(1)
    if not rest or rest[0] in ",.!;:-" or rest.split()[0] in NO_FOLLOWERS:
        return "no"
    return None


def abort(op):
    return "after an aborted turn" if op["prev_stop"] == "aborted" else None


SIGNALS = {"approval": approval, "status-check": status_check, "correction": correction, "abort": abort}


def shingles(text):
    words = re.findall(r"[\w']+", text.lower())
    if len(words) < SHINGLE:
        return frozenset([" ".join(words)])
    return frozenset(" ".join(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1))


def jaccard(a, b):
    return len(a & b) / len(a | b) if a or b else 1.0


def cluster(sets, threshold):
    """Group indexes of sets whose Jaccard similarity is at least threshold, transitively.

    Exact: identical sets merge first, then every pair of distinct sets that shares a shingle
    is compared, skipping pairs whose sizes alone rule the threshold out
    (Jaccard <= min/max size). A periodic report over a few thousand messages runs in seconds.
    """
    same = defaultdict(list)
    for i, s in enumerate(sets):
        same[s].append(i)
    uniq = list(same)
    parent = list(range(len(uniq)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    index = defaultdict(list)
    for i, s in enumerate(uniq):
        for x in s:
            index[x].append(i)
    for i, s in enumerate(uniq):
        cand = set()
        for x in s:
            posting = index[x]
            cand.update(posting[bisect.bisect_right(posting, i):])
        n = len(s)
        for j in cand:
            m = len(uniq[j])
            if min(n, m) / max(n, m) < threshold or find(i) == find(j):
                continue
            if jaccard(s, uniq[j]) >= threshold:
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i, s in enumerate(uniq):
        groups[find(i)].extend(same[s])
    return [sorted(g) for g in groups.values()]


def example(rel, op, max_chars, context=False):
    ex = {"session": rel, "timestamp": op["ts"], "text": short(op["text"], max_chars),
          "agent": tail(op["agent"], max_chars)}
    if context:
        ex["after"] = short(op.get("after", ""), max_chars)
    return ex


def bucket(words):
    for name, lo, hi in BUCKETS:
        if words >= lo and (hi is None or words <= hi):
            return name
    return BUCKETS[-1][0]


def analyze(src, since, cwd_match=(), min_sessions=2, examples=6, max_chars=240, context=False):
    notes, missing = [], []
    totals = {"sessions": 0, "skipped_subagent": 0, "skipped_out_of_window": 0, "skipped_cwd": 0,
              "skipped_no_operator_text": 0, "operator_messages": 0}
    root = src["sessions"]
    sessions = {}
    if not os.path.isdir(root):
        missing.append(f"pi sessions: not found ({root})")
    else:
        cutoff = since.timestamp()
        for p in sorted(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)):
            if SUBAGENT.search(p.replace(os.sep, "/")):
                totals["skipped_subagent"] += 1
                continue
            try:
                if os.path.getmtime(p) < cutoff:
                    totals["skipped_out_of_window"] += 1
                    continue
            except OSError:
                continue
            cwd, users, ops = read_session(p, since, src, notes)
            if not users:
                totals["skipped_out_of_window"] += 1
            elif cwd_match and not (cwd and any(t in cwd for t in cwd_match)):
                totals["skipped_cwd"] += 1
            elif not ops:
                totals["skipped_no_operator_text"] += 1
            else:
                sessions[os.path.relpath(p, root)] = ops
    totals["sessions"] = len(sessions)
    totals["operator_messages"] = sum(len(o) for o in sessions.values())

    hits = {name: defaultdict(list) for name in SIGNALS}
    flagged = set()
    skill_count, skill_sessions, no_skill = Counter(), defaultdict(set), 0
    for rel, ops in sessions.items():
        used = False
        for op in ops:
            for s in op["skills"]:
                skill_count[s] += 1
                skill_sessions[s].add(rel)
                used = True
            for name, fn in SIGNALS.items():
                key = fn(op)
                if key:
                    hits[name][key].append((rel, op))
                    if name in ("approval", "correction"):
                        flagged.add(rel)
        no_skill += not used

    report = {"since": since.date().isoformat(), "totals": totals, "missing": missing}
    for name in SIGNALS:
        groups = []
        for key, items in hits[name].items():
            sess = {r for r, _ in items}
            if len(sess) < min_sessions:
                continue
            groups.append({"key": key, "sessions": len(sess), "count": len(items),
                           "examples": [example(r, op, max_chars, context) for r, op in items[:examples]]})
        groups.sort(key=lambda g: (-g["sessions"], -g["count"], g["key"]))
        all_items = [x for items in hits[name].values() for x in items]
        report[name] = {"sessions": len({r for r, _ in all_items}), "count": len(all_items), "groups": groups}

    long_ops = [(rel, op) for rel, ops in sessions.items() for op in ops if len(op["text"]) >= REPEAT_MIN_CHARS]
    groups, repeat_sessions = [], set()
    for members in cluster([shingles(op["text"]) for _, op in long_ops], REPEAT_THRESHOLD):
        items = [long_ops[i] for i in sorted(members)]
        sess = {r for r, _ in items}
        if len(sess) < max(2, min_sessions):
            continue
        repeat_sessions |= sess
        groups.append({"key": short(items[0][1]["text"], 80), "sessions": len(sess), "count": len(items),
                       "examples": [example(r, op, max_chars, context) for r, op in items[:examples]]})
    groups.sort(key=lambda g: (-g["sessions"], -g["count"], g["key"]))
    report["repeat"] = {"sessions": len(repeat_sessions),
                        "count": sum(g["count"] for g in groups), "groups": groups}

    report["skills"] = {
        "skills": sorted(({"name": s, "sessions": len(skill_sessions[s]), "count": c} for s, c in skill_count.items()),
                         key=lambda r: (-r["sessions"], -r["count"], r["name"])),
        "sessions_without_skill": no_skill,
    }

    by_bucket = defaultdict(list)
    for rel, ops in sessions.items():
        by_bucket[bucket(len(ops[0]["text"].split()))].append(rel)
    shape = []
    for name, lo, hi in BUCKETS:
        rels = by_bucket.get(name, [])
        shape.append({"bucket": name, "words": f"{lo}-{hi}" if hi is not None else f"{lo}+", "sessions": len(rels),
                      "median_messages": statistics.median(len(sessions[r]) for r in rels) if rels else 0,
                      "flagged_share": round(sum(r in flagged for r in rels) / len(rels), 2) if rels else 0.0})
    report["prompt-shape"] = shape
    return report, notes


def print_text(report):
    t = report["totals"]
    print(f"Operator signals since {report['since']}: {t['sessions']} sessions, {t['operator_messages']} operator "
          f"messages")
    print(f"skipped: {t['skipped_subagent']} subagent, {t['skipped_out_of_window']} out of window, "
          f"{t['skipped_no_operator_text']} no operator text, {t['skipped_cwd']} cwd mismatch")
    for m in report["missing"]:
        print(f"missing: {m}")
    for name in list(SIGNALS) + ["repeat"]:
        sec = report[name]
        print(f"\n== {name} == ({sec['sessions']} sessions, {sec['count']} messages)")
        if not sec["groups"]:
            print("  (none)")
        for g in sec["groups"]:
            print(f"{g['sessions']:>5} {g['count']:>5}  {g['key']}")
            for e in g["examples"]:
                print(f"             {e['session']} {e['timestamp']}")
                print(f"               you: {e['text']}")
                if e["agent"]:
                    print(f"               agent before: {e['agent']}")
                if e.get("after"):
                    print(f"               agent after: {e['after']}")
    sk = report["skills"]
    print(f"\n== skills == ({sk['sessions_without_skill']} sessions with no skill invocation)")
    if not sk["skills"]:
        print("  (none)")
    for r in sk["skills"]:
        print(f"{r['sessions']:>5} {r['count']:>5}  {r['name']}")
    print("\n== prompt-shape == (first operator message, words)")
    print(f"{'bucket':<8} {'words':>7} {'sess':>5} {'median msgs':>12} {'corr/appr share':>16}")
    for r in report["prompt-shape"]:
        print(f"{r['bucket']:<8} {r['words']:>7} {r['sessions']:>5} {r['median_messages']:>12} "
              f"{r['flagged_share']:>16}")


def main(argv=None):
    load_env_files()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 usage=argparse.SUPPRESS)
    ap.add_argument("--since", default="14d", help="YYYY-MM-DD or Nd (default 14d)")
    ap.add_argument("--cwd-match", action="append", default=[], help="keep sessions whose cwd contains TEXT")
    ap.add_argument("--min-sessions", type=int, default=2, help="hide groups seen in fewer sessions (default 2)")
    ap.add_argument("--examples", type=int, default=6, help="examples per group (default 6)")
    ap.add_argument("--max-chars", type=int, default=240, help="excerpt length (default 240)")
    ap.add_argument("--context", action="store_true",
                    help="add the start of the agent's next text after each example message")
    ap.add_argument("--json", action="store_true", help="print the report as one JSON object")
    args = ap.parse_args(argv)
    report, notes = analyze(sources(), parse_since(args.since), args.cwd_match, args.min_sessions, args.examples,
                            args.max_chars, args.context)
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print_text(report)
    for n in notes:
        print(f"note: {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
