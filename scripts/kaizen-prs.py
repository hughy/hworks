#!/usr/bin/env python3
"""Report what happened to the PRs agents opened or touched in pi sessions: outcome, rework,
review, test share, and where session time went.

Read-only. Output quotes private content (PR titles, URLs, session paths): do not redirect it
into a repo.
usage: kaizen-prs.py [--since YYYY-MM-DD|Nd] [--top N] [--cwd-match TEXT]... [--no-fetch] [--json]

Links: a session links to a PR (https://<host>/<owner>/<repo>/pull/<n>) with a role:
  opened   a bash call whose command contains `gh pr create`; the PR is the first PR URL in
           its tool result.
  touched  a PR URL in a bash command that runs `gh pr <subcommand>`, or in the arguments of a
           tool named in HWORKS_PR_TOOLS.
Each (session, PR, role) counts once, at its first timestamp. A child session is
<session>/<run id>/run-N/session.jsonl; every other transcript is a main session.

Each linked PR is fetched once with `gh pr view <url> --json ...` (timeout GH_TIMEOUT seconds).
A failed fetch is recorded per host with the first line of stderr, never fatal. --no-fetch
skips gh and reports links only.

Sections:
  coverage  sessions scanned (main, child), sessions with a link, links by role, PRs found,
            PRs fetched and failed per host with the error, sessions with no link that pushed
            a branch other than main, master, or trunk (a gap in PR linking, not a finding),
            and every missing source. A push's branches are the destinations in its result's
            ref update lines (`<old>..<new>  <src> -> <dst>`, `* [new branch]  <src> -> <dst>`);
            with no such line, the refspecs in its command; a push naming no branch either
            counts.
  outcomes  merged, closed unmerged, open, and draft (a subset of open) counts. One row per
            PR, worst rework first, cut by --top: state, opening session, other linking
            sessions, commits after the PR was created, changes-requested reviews, non-empty
            review and comment bodies by others than the author, failing and pending checks in
            the final rollup, and hours from creation to first review by someone else, from
            creation to merge or close, and from last commit to merge. Rework, the ordering
            key, is commits after creation + changes-requested reviews + failing final checks;
            each part is printed. PRs not fetched follow, with links only.
  tests     per fetched PR, lines added and deleted in test files against production files.
            A test file matches TEST_FILE in kaizen-sessions.py, sits under a test/, tests/, or
            __tests__/ directory, or ends in _test.go or .t.sol. Two leads, to read, not
            violations: test lines added exceed twice production lines added (at least
            LEAD_MIN_TESTS), and production changes under SMALL_PROD lines with over
            BIG_TESTS test lines added.
  time      from transcripts, per main session and in total, children summed apart, each gap
            between consecutive messages in the window goes to one bucket by the message that
            ends it: model (an assistant message), tool by tool name (a tool result), human
            (a user message the operator typed), harness (a user message matching
            HWORKS_OPERATOR_SKIP, or any other role). A gap over IDLE_MINUTES is idle instead.
            These buckets sum to the session's wall time. Per-tool latency (count, total,
            median seconds) pairs each tool result with its call by toolCallId and runs from
            the call's assistant message to the result. Latencies of batched or parallel calls
            overlap, so they do not sum to wall time.
            From gh: median hours from creation to first review, creation to merge, last
            commit to merge, and the final CI run's span (latest completedAt minus earliest
            startedAt in the rollup).

Sources (each optional; a missing one is reported, not fatal):
  HWORKS_PI_SESSIONS    pi session transcripts, **/*.jsonl (default ~/.pi/agent/sessions);
                        subagent-artifacts/ copies are skipped
  HWORKS_PR_TOOLS       comma-separated tool names whose arguments link PRs (default none),
                        for example a harness's PR-tracking tool
  HWORKS_OPERATOR_SKIP  regex; a user message whose text matches it (re.search) is not typed
                        by the operator, as in operator-signals.py
  HWORKS_GH             gh binary (default gh)
adapters/local/*.env, when present, is read first; values already in the environment win.
"""
import argparse
import glob
import importlib.util
import json
import os
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ks = _load("kaizen_sessions", "kaizen-sessions.py")
kt = _load("kaizen_tokens", "kaizen-tokens.py")

PR_URL = re.compile(r"https://([\w.-]+)/([\w.-]+)/([\w.-]+)/pull/(\d+)")
GH_PR = re.compile(r"\bgh\s+pr\s+[a-z]")
GIT_PUSH = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?push\b([^;&|\n]*)")
REF_UPDATE = re.compile(r"^\s*[+*]?\s*(?:[0-9a-f]+\.\.\.?[0-9a-f]+|\[new branch\])\s+\S+\s+->\s+(\S+)", re.M)
DEFAULT_BRANCHES = {"main", "master", "trunk"}
PUSH_VALUE_OPTS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
FIELDS = ("number,title,state,isDraft,createdAt,mergedAt,closedAt,additions,deletions,files,commits,"
          "reviews,comments,statusCheckRollup,author")
GH_TIMEOUT = 60
IDLE_MINUTES = 30
LEAD_MIN_TESTS = 20
SMALL_PROD = 10
BIG_TESTS = 50
FAILING = {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"}
PENDING = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"}


def pr_urls(text):
    return [f"https://{h}/{o}/{r}/pull/{n}" for h, o, r, n in PR_URL.findall(text or "")]


def host_of(url):
    return url.split("/")[2]


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text") or "" for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def push_branches(args):
    """Branches named by the refspecs in the text after `git push`: the destination of each
    refspec after the remote, with HEAD and options (and their separate values) dropped."""
    words, it = [], iter(args.split())
    for w in it:
        if w in PUSH_VALUE_OPTS:
            next(it, None)
        elif not w.startswith("-"):
            words.append(w)
    out = []
    for w in words[1:]:
        dst = w.lstrip("+").split(":")[-1].removeprefix("refs/heads/")
        if dst and dst != "HEAD" and not dst.startswith("refs/"):
            out.append(dst)
    return out


def pushed_branch(args, result):
    """Whether one push updated, or names, a branch other than a default one (see coverage)."""
    branches = [b.removeprefix("refs/heads/") for b in REF_UPDATE.findall(result)] or push_branches(args)
    return not branches or any(b not in DEFAULT_BRANCHES for b in branches)


def read_session(path, since, pr_tools, notes):
    """The session's cwd, its messages in the window (ts, role, tool name, latency for a tool
    result, operator text), its links as {(url, role): ts}, and whether it pushed a non-default
    branch."""
    s = {"cwd": None, "messages": [], "links": {}, "pushed": False}
    creates, calls, pushes = {}, {}, {}
    bad = 0
    try:
        f = open(path, errors="replace")
    except OSError as e:
        notes.append(f"{path}: {e}")
        return s
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
                s["cwd"] = e.get("cwd") if isinstance(e.get("cwd"), str) else None
                continue
            m = e.get("message")
            if e.get("type") != "message" or not isinstance(m, dict):
                continue
            ts = ks.to_dt(e.get("timestamp") or m.get("timestamp"))
            if ts is None or ts < since:
                continue
            role = m.get("role")
            msg = {"ts": ts, "role": role, "tool": m.get("toolName") or "?", "text": ""}
            s["messages"].append(msg)

            def link(url, r):
                s["links"].setdefault((url, r), ts)

            if role == "assistant":
                for c in m.get("content") or []:
                    if not isinstance(c, dict) or c.get("type") != "toolCall":
                        continue
                    args = c.get("arguments") if isinstance(c.get("arguments"), dict) else {}
                    name = c.get("name")
                    cmd = args.get("command") if isinstance(args.get("command"), str) else ""
                    if c.get("id"):
                        calls[c["id"]] = ts
                    if name == "bash":
                        if "gh pr create" in cmd and c.get("id"):
                            creates[c["id"]] = True
                        push_args = GIT_PUSH.findall(cmd)
                        if push_args and c.get("id"):
                            pushes[c["id"]] = push_args
                        elif push_args:
                            s["pushed"] |= any(pushed_branch(a, "") for a in push_args)
                        if GH_PR.search(cmd):
                            for u in pr_urls(cmd):
                                link(u, "touched")
                    elif name in pr_tools:
                        for u in pr_urls(json.dumps(args)):
                            link(u, "touched")
            elif role == "toolResult":
                cid = m.get("toolCallId")
                if cid in calls:
                    msg["latency"] = (ts - calls.pop(cid)).total_seconds()
                if cid in pushes:
                    text = text_of(m.get("content"))
                    s["pushed"] |= any(pushed_branch(a, text) for a in pushes.pop(cid))
                if creates.pop(cid, False):
                    urls = pr_urls(text_of(m.get("content")))
                    if urls:
                        link(urls[0], "opened")
            elif role == "user":
                msg["text"] = text_of(m.get("content"))
    s["pushed"] |= any(pushed_branch(a, "") for ps in pushes.values() for a in ps)
    if bad:
        notes.append(f"{path}: skipped {bad} malformed line(s)")
    return s


def time_split(messages, skip):
    """Seconds by bucket for one session's messages (see the time section in the docstring)."""
    out = Counter()
    tools = Counter()
    latency = defaultdict(list)
    for m in messages:
        if "latency" in m:
            latency[m["tool"]].append(m["latency"])
    for prev, cur in zip(messages, messages[1:]):
        gap = (cur["ts"] - prev["ts"]).total_seconds()
        if gap <= 0:
            continue
        if gap > IDLE_MINUTES * 60:
            out["idle"] += gap
        elif cur["role"] == "assistant":
            out["model"] += gap
        elif cur["role"] == "toolResult":
            out["tool"] += gap
            tools[cur["tool"]] += gap
        elif cur["role"] == "user" and not (skip and skip.search(cur["text"])):
            out["human"] += gap
        else:
            out["harness"] += gap
    return {"model": out["model"], "tool": out["tool"], "tools": dict(tools), "human": out["human"],
            "harness": out["harness"], "idle": out["idle"], "latency": dict(latency)}


def add_split(a, b):
    for k in ("model", "tool", "human", "harness", "idle"):
        a[k] = a.get(k, 0) + b[k]
    tools = a.setdefault("tools", {})
    for k, v in b["tools"].items():
        tools[k] = tools.get(k, 0) + v
    lat = a.setdefault("latency", {})
    for k, v in b["latency"].items():
        lat[k] = lat.get(k, []) + v
    return a


def summarize_latency(sp):
    """Replace a split's raw per-tool latencies with count, total, and median seconds."""
    if sp:
        sp["latency"] = {k: {"count": len(v), "total": sum(v), "median": median(v)}
                         for k, v in sorted(sp["latency"].items())}
    return sp


def fetch(url, gh):
    """(data, None) or (None, first stderr line)."""
    try:
        p = subprocess.run([gh, "pr", "view", url, "--json", FIELDS], capture_output=True, text=True,
                           timeout=GH_TIMEOUT)
    except FileNotFoundError:
        return None, f"{gh}: not found"
    except subprocess.TimeoutExpired:
        return None, f"timed out after {GH_TIMEOUT}s"
    if p.returncode != 0:
        lines = [x for x in p.stderr.splitlines() if x.strip()]
        return None, lines[0].strip() if lines else f"exit {p.returncode}"
    try:
        return json.loads(p.stdout), None
    except ValueError:
        return None, "unparseable gh output"


def hours(a, b):
    a, b = ks.to_dt(a) if a else None, ks.to_dt(b) if b else None
    return round((b - a).total_seconds() / 3600, 1) if a and b else None


def login(x):
    return ((x or {}).get("author") or {}).get("login")


def checks(rollup):
    failing, pending = [], []
    for c in rollup or []:
        name = c.get("name") or c.get("context") or "?"
        if c.get("__typename") == "StatusContext" or "context" in c:
            st = c.get("state")
            (failing if st in FAILING else pending if st in PENDING else []).append(name)
        elif c.get("status") and c.get("status") != "COMPLETED":
            pending.append(name)
        elif c.get("conclusion") in FAILING:
            failing.append(name)
    return failing, pending


def ci_span(rollup):
    starts = [ks.to_dt(c["startedAt"]) for c in rollup or [] if c.get("startedAt")]
    ends = [ks.to_dt(c["completedAt"]) for c in rollup or [] if c.get("completedAt")]
    starts, ends = [x for x in starts if x], [x for x in ends if x]
    return round((max(ends) - min(starts)).total_seconds() / 3600, 2) if starts and ends else None


def outcome(d):
    author = login(d)
    created = d.get("createdAt")
    cdt = ks.to_dt(created) if created else None
    commit_dates = [x for x in (ks.to_dt(c.get("committedDate")) for c in d.get("commits") or []
                                if c.get("committedDate")) if x]
    after = sum(1 for x in commit_dates if cdt and x > cdt)
    reviews = d.get("reviews") or []
    changes = sum(1 for r in reviews if r.get("state") == "CHANGES_REQUESTED")
    feedback = sum(1 for r in reviews + (d.get("comments") or [])
                   if (r.get("body") or "").strip() and login(r) != author)
    others = sorted(r["submittedAt"] for r in reviews if login(r) != author and r.get("submittedAt"))
    failing, pending = checks(d.get("statusCheckRollup"))
    last_commit = max(commit_dates).isoformat() if commit_dates else None
    return {"state": d.get("state"), "draft": bool(d.get("isDraft")), "title": d.get("title") or "",
            "commits_after_create": after, "changes_requested": changes, "feedback_bodies": feedback,
            "failing_checks": failing, "pending_checks": pending,
            "rework": after + changes + len(failing),
            "hours_to_first_review": hours(created, others[0]) if others else None,
            "hours_to_close": hours(created, d.get("mergedAt") or d.get("closedAt")),
            "hours_last_commit_to_merge": hours(last_commit, d.get("mergedAt")),
            "ci_span_hours": ci_span(d.get("statusCheckRollup"))}


def is_test(path):
    parts = path.split("/")
    return bool(ks.TEST_FILE.search(parts[-1]) or set(parts[:-1]) & {"test", "tests", "__tests__"}
                or path.endswith(("_test.go", ".t.sol")))


def test_share(files):
    t = Counter()
    for f in files or []:
        kind = "test" if is_test(f.get("path") or "") else "prod"
        t[kind + "_add"] += f.get("additions") or 0
        t[kind + "_del"] += f.get("deletions") or 0
    row = {k: t[k] for k in ("test_add", "test_del", "prod_add", "prod_del")}
    leads = []
    if row["test_add"] > 2 * row["prod_add"] and row["test_add"] >= LEAD_MIN_TESTS:
        leads.append("tests > 2x production lines")
    if row["prod_add"] + row["prod_del"] < SMALL_PROD and row["test_add"] > BIG_TESTS:
        leads.append(f"production < {SMALL_PROD} lines, tests > {BIG_TESTS}")
    row["leads"] = leads
    return row


def median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def analyze(src, since, top=15, cwd_match=(), fetch_prs=True, gh="gh", pr_tools=(), skip=None):
    notes, missing = [], []
    sroot = src["sessions"]
    if not os.path.isdir(sroot):
        missing.append(f"pi sessions: not found ({sroot})")
        return {"coverage": {"missing_sources": missing}, "outcomes": {}, "tests": [], "time": {}}, notes
    cutoff = since.timestamp()
    sessions = {}
    for p in sorted(glob.glob(os.path.join(sroot, "**", "*.jsonl"), recursive=True)):
        if "/subagent-artifacts/" in p:
            continue
        try:
            if os.path.getmtime(p) < cutoff:
                continue
        except OSError:
            continue
        s = read_session(p, since, pr_tools, notes)
        if not s["messages"]:
            continue
        rel = os.path.relpath(p, sroot)
        if cwd_match and not any(m.lower() in (s["cwd"] or rel).lower() for m in cwd_match):
            continue
        s["kind"] = "child" if kt.CHILD.search(p) else "main"
        sessions[rel] = s

    prs = defaultdict(list)
    for rel, s in sessions.items():
        for (url, role), ts in s["links"].items():
            prs[url].append({"session": rel, "role": role, "ts": ts.isoformat()})
    roles = Counter(l["role"] for ls in prs.values() for l in ls)

    data, hosts = {}, defaultdict(lambda: {"fetched": 0, "failed": 0, "error": None})
    if fetch_prs:
        for url in sorted(prs):
            d, err = fetch(url, gh)
            h = hosts[host_of(url)]
            if d is None:
                h["failed"] += 1
                h["error"] = h["error"] or err
            else:
                h["fetched"] += 1
                data[url] = d

    coverage = {
        "sessions_main": sum(1 for s in sessions.values() if s["kind"] == "main"),
        "sessions_child": sum(1 for s in sessions.values() if s["kind"] == "child"),
        "sessions_linked": sum(1 for s in sessions.values() if s["links"]),
        "links_by_role": dict(sorted(roles.items())),
        "prs_found": len(prs),
        "fetch": "skipped (--no-fetch)" if not fetch_prs else dict(sorted(hosts.items())),
        "pushed_without_link": sorted(rel for rel, s in sessions.items() if s["pushed"] and not s["links"]),
        "missing_sources": missing,
    }

    rows, unfetched = [], []
    for url, links in prs.items():
        links.sort(key=lambda l: l["ts"])
        opener = next((l["session"] for l in links if l["role"] == "opened"), None)
        others = sorted({l["session"] for l in links} - {opener})
        base = {"url": url, "opened_by": opener, "other_sessions": others}
        if url in data:
            rows.append({**base, **outcome(data[url])})
        else:
            unfetched.append(base)
    rows.sort(key=lambda r: (-r["rework"], r["url"]))
    unfetched.sort(key=lambda r: r["url"])
    states = Counter(r["state"] for r in rows)
    outcomes = {"merged": states["MERGED"], "closed_unmerged": states["CLOSED"], "open": states["OPEN"],
                "draft": sum(1 for r in rows if r["draft"] and r["state"] == "OPEN"),
                "rows": rows[:top], "unfetched": unfetched[:top]}

    tests = [{"url": url, **test_share(d.get("files"))} for url, d in data.items()]
    tests.sort(key=lambda r: (-len(r["leads"]), -r["test_add"], r["url"]))

    per_session, total_main, total_child = [], {}, {}
    for rel, s in sessions.items():
        sp = time_split(s["messages"], skip)
        if s["kind"] == "main":
            add_split(total_main, sp)
            per_session.append({"session": rel, **summarize_latency(dict(sp))})
        else:
            add_split(total_child, sp)
    summarize_latency(total_main)
    summarize_latency(total_child)
    per_session.sort(key=lambda r: (-(r["model"] + r["tool"] + r["human"] + r["harness"]), r["session"]))
    time = {
        "transcripts": {"main_total": total_main, "child_total": total_child, "sessions": per_session[:top]},
        "gh": {"median_hours_to_first_review": median(r["hours_to_first_review"] for r in rows),
               "median_hours_to_close": median(r["hours_to_close"] for r in rows if r["state"] == "MERGED"),
               "median_hours_last_commit_to_merge": median(r["hours_last_commit_to_merge"] for r in rows),
               "median_ci_span_hours": median(r["ci_span_hours"] for r in rows),
               "prs": len(rows)},
    }
    return {"coverage": coverage, "outcomes": outcomes, "tests": tests[:top], "time": time}, notes


def h(sec):
    return f"{sec / 3600:.1f}h"


def opt(x):
    return "-" if x is None else x


def print_text(r, since):
    c = r["coverage"]
    print(f"PRs from pi sessions since {since.date()}")
    print("\n== coverage ==")
    for m in c["missing_sources"]:
        print(f"  missing source: {m}")
    if "sessions_main" not in c:
        return
    print(f"  sessions: {c['sessions_main']} main, {c['sessions_child']} child; {c['sessions_linked']} with a link")
    print(f"  links: {', '.join(f'{k} {n}' for k, n in c['links_by_role'].items()) or 'none'}; "
          f"PRs found: {c['prs_found']}")
    if isinstance(c["fetch"], str):
        print(f"  fetch: {c['fetch']}")
    for host, f in c["fetch"].items() if isinstance(c["fetch"], dict) else ():
        err = f"  error: {f['error']}" if f["error"] else ""
        print(f"  {host}: {f['fetched']} fetched, {f['failed']} failed{err}")
    print("  pushed a branch other than main/master/trunk with no PR link (a linking gap, not a finding): "
          f"{len(c['pushed_without_link'])}")
    for s in c["pushed_without_link"]:
        print(f"    {s}")

    o = r["outcomes"]
    print("\n== outcomes ==  (from gh; rework = commits after create + changes requested + failing checks)")
    print(f"  merged {o['merged']}, closed unmerged {o['closed_unmerged']}, open {o['open']} "
          f"(draft {o['draft']})")
    for p in o["rows"]:
        state = p["state"] + (" draft" if p["draft"] else "")
        print(f"  {p['url']}  [{state}] rework {p['rework']}: commits after create {p['commits_after_create']}, "
              f"changes requested {p['changes_requested']}, failing checks {len(p['failing_checks'])}")
        print(f"      {p['title']}")
        print(f"      opened by: {p['opened_by'] or '-'}; also linked: {', '.join(p['other_sessions']) or '-'}")
        print(f"      feedback bodies by others: {p['feedback_bodies']}; failing: "
              f"{', '.join(p['failing_checks']) or '-'}; pending: {', '.join(p['pending_checks']) or '-'}")
        print(f"      hours: to first review {opt(p['hours_to_first_review'])}, to merge/close "
              f"{opt(p['hours_to_close'])}, last commit to merge {opt(p['hours_last_commit_to_merge'])}")
    for p in o["unfetched"]:
        print(f"  {p['url']}  [not fetched] opened by: {p['opened_by'] or '-'}; "
              f"also linked: {', '.join(p['other_sessions']) or '-'}")

    print("\n== tests ==  (lines added/deleted; leads are to read, not violations)")
    if not r["tests"]:
        print("  (none fetched)")
    for t in r["tests"]:
        lead = f"  lead: {'; '.join(t['leads'])}" if t["leads"] else ""
        print(f"  test +{t['test_add']}/-{t['test_del']}  prod +{t['prod_add']}/-{t['prod_del']}  {t['url']}{lead}")

    tm = r["time"]
    print("\n== time ==  (transcripts: when entries were written, not wall-clock work)")

    def line(label, sp):
        if not sp:
            print(f"  {label}: -")
            return
        tools = ", ".join(f"{k} {h(v)}" for k, v in sorted(sp["tools"].items(), key=lambda kv: -kv[1]))
        print(f"  {label}: model {h(sp['model'])}, tool {h(sp['tool'])}, human {h(sp['human'])}, "
              f"harness {h(sp['harness'])}, idle {h(sp['idle'])}" + (f"  [{tools}]" if tools else ""))
        if sp["latency"]:
            print("    tool latency (overlaps for batched calls): " + ", ".join(
                f"{k} {v['count']}x total {h(v['total'])} median {v['median']}s" for k, v in sp["latency"].items()))

    line("main total", tm["transcripts"]["main_total"])
    line("child total", tm["transcripts"]["child_total"])
    for sp in tm["transcripts"]["sessions"]:
        line(sp["session"], sp)
    g = tm["gh"]
    print(f"  from gh over {g['prs']} PRs, median hours: to first review {opt(g['median_hours_to_first_review'])}, "
          f"to merge {opt(g['median_hours_to_close'])}, last commit to merge "
          f"{opt(g['median_hours_last_commit_to_merge'])}, final CI span {opt(g['median_ci_span_hours'])}")


def main(argv=None):
    ks.load_env_files(ROOT)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 usage=argparse.SUPPRESS)
    ap.add_argument("--since", default="14d", help="YYYY-MM-DD or Nd (default 14d)")
    ap.add_argument("--top", type=int, default=15, help="rows per ranked section (default 15)")
    ap.add_argument("--cwd-match", action="append", default=[], metavar="TEXT",
                    help="keep sessions whose cwd contains TEXT (repeatable)")
    ap.add_argument("--no-fetch", action="store_true", help="skip gh; report links only")
    ap.add_argument("--json", action="store_true", help="one JSON object")
    args = ap.parse_args(argv)
    try:
        since = ks.parse_since(args.since)
    except ValueError:
        ap.error(f"--since: expected YYYY-MM-DD or Nd, got {args.since!r}")
    pr_tools = {t.strip() for t in (os.environ.get("HWORKS_PR_TOOLS") or "").split(",") if t.strip()}
    skip = os.environ.get("HWORKS_OPERATOR_SKIP")
    report, notes = analyze(ks.sources(), since, args.top, args.cwd_match, not args.no_fetch,
                            os.environ.get("HWORKS_GH") or "gh", pr_tools, re.compile(skip, re.S) if skip else None)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_text(report, since)
    for n in notes:
        print(f"note: {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
