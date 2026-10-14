#!/usr/bin/env python3
"""Find patterns in how the operator works with agents, from the operator's own messages in pi,
Claude Code, and Codex CLI transcripts.

Read-only. Reads only sessions the operator started (subagent transcripts are skipped) and,
in them, the messages the operator typed, with harness injections removed. Reports signals
ranked by distinct sessions, each with counts and examples that quote the operator's message
and the end of the agent's last text before it (with --context, also the start of the agent's
next text after it). Every quoted excerpt is redacted first (see Redaction), but output still
quotes private prompts and transcript content: do not redirect it into a repo.
usage: operator-signals.py [--since YYYY-MM-DD|Nd] [--cwd-match TEXT]... [--min-sessions N]
                           [--examples N] [--max-chars N] [--context] [--json]

Sources (each optional; a missing one is reported, not fatal):
  HWORKS_PI_SESSIONS      pi session transcripts, **/*.jsonl (default ~/.pi/agent/sessions)
  HWORKS_CLAUDE_SESSIONS  Claude Code transcripts, **/*.jsonl (default ~/.claude/projects)
  HWORKS_CODEX_SESSIONS   Codex CLI transcripts, **/*.jsonl (default ~/.codex/sessions)
  HWORKS_OPERATOR_SKIP    regex; a user message whose raw text matches it (re.search) is not
                          operator-authored, for example an automation ping, and is dropped
  HWORKS_INJECTED_PREFIX  regex for more leading injected text to strip (re.match, repeated)
  HWORKS_REDACT           regex; each match in an excerpt becomes [redacted:custom]
adapters/local/*.env, when present, is read first to set any of these; values already in the
environment win. Session keys carry the harness as a prefix (pi:, claude:, codex:), and the
header gives sessions and operator messages per harness.

Scope: a pi transcript under /subagent-artifacts/, named *_transcript.jsonl, or at
run-<N>/session.jsonl is a subagent's and is skipped, as is a Claude Code transcript under a
subagents/ directory or a line marked isSidechain, and a Codex session whose session_meta
thread_source is set and not "user". --since drops messages before it, and a session with no
user message after it counts as out of window. --cwd-match keeps sessions whose recorded cwd
contains any of the given strings. Operator text is a user message's text after leading
injections are removed: a <skill name="X" ...>...</skill> block (an invocation of skill X,
counted under skills), any other leading <tag ...>...</tag> block, and HWORKS_INJECTED_PREFIX
matches. A message left with no text and no skill invocation is not an operator message; a
session with no operator message is skipped.

Per harness, a user message is operator-typed when:
  pi      it is a message with role "user".
  claude  it is a type "user" line whose content is a string or holds text parts (a list of
          only tool_result parts is a tool result), not isMeta, with promptSource absent or
          "typed" and origin.kind absent or "human". A text starting "[Request interrupted by
          user" is not one: it marks the previous turn aborted. Lines repeating a uuid already
          read are skipped.
  codex   it is an event_msg user_message (response_item user messages duplicate it and carry
          injected AGENTS.md and environment text). Agent text is event_msg agent_message.
The previous turn's stop is normalized to pi's stopReason: "stop" when it ended and waited for
the operator (pi "stop", Claude end_turn, Codex task_complete), "aborted" when the operator
interrupted it (pi "aborted", the Claude interrupt marker, Codex turn_aborted).

Redaction: operator text and agent excerpts are redacted before they are stored, so signals
and output both see the redacted text. Each hit becomes [redacted:<kind>]: private-key blocks,
jwt, github-token (gh[pousr]_, github_pat_), slack-token (xox[abprs]-), aws-key (AKIA/ASIA
ids), bearer tokens, url-credentials (user:pass@ in a URL), secret (the value of a
key/token/secret/password-style assignment), email, and custom (HWORKS_REDACT). Patterns
catch common shapes only; read output before sharing it.

Signals (groups below --min-sessions are hidden, except skills and prompt-shape):
  approval      a bare consent of at most APPROVAL_MAX_WORDS words (yes, ok, go ahead, lgtm,
                ...) right after an assistant turn that ended (stop "stop"): the agent
                stopped to ask permission. Grouped by the normalized phrase.
  status-check  a message of at most STATUS_MAX_WORDS words that, normalized, is wholly a
                progress query (status?, any update, checking progress, how's it going, ...),
                so "show git status" or "add a progress bar" is not one. Grouped by phrase.
  correction    a message whose opening matches a correction cue (no, actually, wrong, I
                meant, revert, ...), grouped by cue. A bare "no" counts only alone, before
                punctuation, or before a word in NO_FOLLOWERS, so "no tests fail" is not one.
                A lead: it can mean an unclear prompt or a bad agent turn.
  abort         an operator message right after a turn with stop "aborted": the operator
                interrupted a turn to redirect.
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

CLAUDE_SUBAGENT = re.compile(r"/subagents/")
INTERRUPT = "[Request interrupted by user"
CLAUDE_STOPS = {"end_turn": "stop"}

REDACTIONS = [
    ("private-key", re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S), 0),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), 0),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), 0),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), 0),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
    ("bearer", re.compile(r"(?i)\b(bearer\s+)(?!\[redacted:)([A-Za-z0-9._~+/=-]{12,})"), 2),
    ("url-credentials", re.compile(r"(://)([^/\s:@\[\]]+:[^/\s@]+)(@)"), 2),
    ("secret", re.compile(
        r"(?i)(?<![\w.-])([\w.-]*(?:key|token|secret|password|passwd|pwd)[\w.-]*[\"']?\s*[:=]\s*[\"']?)"
        r"(?!\[redacted:)([^\s\"',;]{4,})"), 2),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"), 0),
]


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


def redact_pattern():
    """HWORKS_REDACT compiled, or None."""
    v = os.environ.get("HWORKS_REDACT")
    return re.compile(v) if v else None


def redact(text, extra=None):
    """text with each secret or personal identifier replaced by [redacted:<kind>]."""
    if not text or not isinstance(text, str):
        return text
    if extra:
        text = extra.sub("[redacted:custom]", text)
    for kind, rx, group in REDACTIONS:
        mark = f"[redacted:{kind}]"
        if group:
            text = rx.sub(lambda m: m.string[m.start():m.start(group)] + mark + m.string[m.end(group):m.end()], text)
        else:
            text = rx.sub(mark, text)
    return text


def sources():
    def rx(name):
        v = os.environ.get(name)
        return re.compile(v, re.S) if v else None
    return {
        "sessions": os.environ.get("HWORKS_PI_SESSIONS") or os.path.expanduser("~/.pi/agent/sessions"),
        "claude": os.environ.get("HWORKS_CLAUDE_SESSIONS") or os.path.expanduser("~/.claude/projects"),
        "codex": os.environ.get("HWORKS_CODEX_SESSIONS") or os.path.expanduser("~/.codex/sessions"),
        "skip": rx("HWORKS_OPERATOR_SKIP"),
        "prefix": rx("HWORKS_INJECTED_PREFIX"),
        "redact": redact_pattern(),
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
    return cwd, users, redact_ops(ops, src)


def redact_ops(ops, src):
    extra = src.get("redact")
    for op in ops:
        for k in ("text", "agent", "after"):
            op[k] = redact(op[k], extra)
    return ops


class Turns:
    """Collects operator messages from one transcript's events, in order, for readers whose
    assistant replies arrive as text events plus separate turn-end events."""

    def __init__(self, since, src):
        self.since, self.src = since, src
        self.users, self.ops, self.waiting, self.filling = 0, [], [], []
        self.last_text, self.last_stop = "", None
        self.cur_id, self.cur_text = None, ""

    def agent_text(self, text, msg_id=None):
        """One assistant text part. Parts sharing msg_id are one reply."""
        text = (text or "").strip()
        if not text:
            return
        if msg_id is not None and msg_id == self.cur_id:
            self.cur_text += "\n" + text
        else:
            self.cur_id, self.cur_text = msg_id, text
            self.filling, self.waiting = self.waiting, []
        self.last_text = self.cur_text
        for op in self.filling:
            op["after"] = self.cur_text

    def stop(self, reason):
        self.last_stop = reason

    def user(self, raw, ts):
        prev_stop, self.last_stop = self.last_stop, None
        self.cur_id = None
        dt = to_dt(ts)
        if dt is None or dt < self.since:
            return
        self.users += 1
        if self.src["skip"] and self.src["skip"].search(raw):
            return
        text, skills = strip_injections(raw, self.src["prefix"])
        if not text and not skills:
            return
        self.ops.append({"text": text, "skills": skills, "ts": dt.isoformat().replace("+00:00", "Z"),
                         "agent": self.last_text, "prev_stop": prev_stop, "after": ""})
        self.waiting.append(self.ops[-1])


def read_jsonl(path, notes):
    """Yields each JSON object line of path; notes unreadable files and malformed lines."""
    bad = 0
    try:
        f = open(path, errors="replace")
    except OSError as e:
        notes.append(f"{path}: {e}")
        return
    with f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(e, dict):
                yield e
    if bad:
        notes.append(f"{path}: skipped {bad} malformed line(s)")


def read_claude(path, since, src, notes, seen):
    """read_session for a Claude Code transcript. seen holds message uuids already read, so a
    resumed session that repeats earlier lines does not count them twice."""
    cwd, t = None, Turns(since, src)
    for e in read_jsonl(path, notes):
        if cwd is None and isinstance(e.get("cwd"), str):
            cwd = e["cwd"]
        m = e.get("message")
        if (e.get("type") not in ("user", "assistant") or not isinstance(m, dict) or e.get("isSidechain")
                or e.get("isMeta")):
            continue
        uid = e.get("uuid")
        if uid is not None:
            if uid in seen:
                continue
            seen.add(uid)
        content = m.get("content")
        if e["type"] == "assistant":
            if isinstance(content, list):
                for p in content:
                    if isinstance(p, dict) and p.get("type") == "text":
                        t.agent_text(p.get("text"), m.get("id"))
            elif isinstance(content, str):
                t.agent_text(content, m.get("id"))
            reason = m.get("stop_reason")
            t.stop(CLAUDE_STOPS.get(reason, reason))
            continue
        if m.get("role") != "user":
            continue
        if isinstance(content, list) and not any(isinstance(p, dict) and p.get("type") == "text" for p in content):
            continue
        origin = e.get("origin")
        if e.get("promptSource") not in (None, "typed") or (
                isinstance(origin, dict) and origin.get("kind") not in (None, "human")):
            continue
        raw = content_text(content)
        if raw.lstrip().startswith(INTERRUPT):
            t.stop("aborted")
            continue
        t.user(raw, e.get("timestamp"))
    return cwd, t.users, redact_ops(t.ops, src)


def read_codex(path, since, src, notes):
    """read_session for a Codex CLI transcript, or None when the operator did not start it."""
    cwd, t = None, Turns(since, src)
    for e in read_jsonl(path, notes):
        p = e.get("payload")
        if not isinstance(p, dict):
            continue
        kind = e.get("type")
        if kind == "session_meta":
            if p.get("thread_source") not in (None, "user"):
                return None
            if isinstance(p.get("cwd"), str):
                cwd = p["cwd"]
        elif kind == "event_msg":
            pt = p.get("type")
            if pt == "user_message" and isinstance(p.get("message"), str):
                t.user(p["message"], e.get("timestamp"))
            elif pt == "agent_message" and isinstance(p.get("message"), str):
                t.agent_text(p["message"])
            elif pt == "task_complete":
                t.stop("stop")
            elif pt == "turn_aborted":
                t.stop("aborted")
    return cwd, t.users, redact_ops(t.ops, src)


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


HARNESSES = [
    ("pi", "sessions", "pi sessions"),
    ("claude", "claude", "Claude Code sessions"),
    ("codex", "codex", "Codex sessions"),
]


def scan(src, since, cwd_match, totals, notes, missing):
    """{"<harness>:<path relative to its root>": operator messages} for every harness whose
    source key is in src, filling totals, notes, and missing."""
    sessions = {}
    cutoff = since.timestamp()
    seen = set()
    for harness, key, label in HARNESSES:
        if key not in src:
            continue
        root = src[key]
        per = totals["harnesses"][harness] = {"sessions": 0, "operator_messages": 0}
        if not root or not os.path.isdir(root):
            missing.append(f"{label}: not found ({root})")
            continue
        for p in sorted(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)):
            slash = p.replace(os.sep, "/")
            if (harness == "pi" and SUBAGENT.search(slash)) or (harness == "claude" and CLAUDE_SUBAGENT.search(slash)):
                totals["skipped_subagent"] += 1
                continue
            try:
                if os.path.getmtime(p) < cutoff:
                    totals["skipped_out_of_window"] += 1
                    continue
            except OSError:
                continue
            if harness == "pi":
                got = read_session(p, since, src, notes)
            elif harness == "claude":
                got = read_claude(p, since, src, notes, seen)
            else:
                got = read_codex(p, since, src, notes)
            if got is None:
                totals["skipped_subagent"] += 1
                continue
            cwd, users, ops = got
            if not users:
                totals["skipped_out_of_window"] += 1
            elif cwd_match and not (cwd and any(t in cwd for t in cwd_match)):
                totals["skipped_cwd"] += 1
            elif not ops:
                totals["skipped_no_operator_text"] += 1
            else:
                sessions[f"{harness}:{os.path.relpath(p, root)}"] = ops
                per["sessions"] += 1
                per["operator_messages"] += len(ops)
    return sessions


def analyze(src, since, cwd_match=(), min_sessions=2, examples=6, max_chars=240, context=False):
    notes, missing = [], []
    totals = {"sessions": 0, "skipped_subagent": 0, "skipped_out_of_window": 0, "skipped_cwd": 0,
              "skipped_no_operator_text": 0, "operator_messages": 0, "harnesses": {}}
    sessions = scan(src, since, cwd_match, totals, notes, missing)
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
    for h, n in t["harnesses"].items():
        print(f"{h}: {n['sessions']} sessions, {n['operator_messages']} operator messages")
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
