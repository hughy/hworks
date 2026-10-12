#!/usr/bin/env python3
"""Bookkeeping for an agent graph: units driven through workflows/review-loop.js, one branch worktree each.

The CLI never launches agents, pushes, deletes a worktree or branch, or discards uncommitted work.
A coordinator runs it, dispatches the workflow itself, and feeds results back with bind and record.

Exit codes: 0 ok, 2 bad input or usage, 3 refused (the store is unchanged unless the message says otherwise).
"""

import argparse
import contextlib
import datetime
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ARGS_SCRIPT = os.path.join(HERE, "review-loop-args.sh")
DEFAULT_WORKFLOW = os.path.normpath(os.path.join(HERE, "..", "workflows", "review-loop.js"))

COLUMNS = ["id", "state", "deps", "paths", "branch", "worktree", "effort", "attempt", "run",
           "start_head", "head", "claim", "reason"]
LIVE = {"launching", "running"}
WORKFLOW_STATES = {"clean", "unresolved", "gate-failed", "review-failed", "blocked"}
# run-failed: the workflow ended without a return value (stopped, failed, cancelled) and no writer is left.
RETRYABLE = {"unresolved", "gate-failed", "review-failed", "run-failed"}
ACCEPTED_UNMERGED = {"clean", "stale", "pr-open"}
SET_TARGETS = {"parked", "abandoned", "queued", "pr-open", "merged"}
EFFORTS = {"quick", "standard", "exhaustive"}
RUNTIME_TERMINAL = {"complete", "completed", "failed", "stopped", "cancelled", "canceled", "error",
                    "timeout", "timed-out", "aborted"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REVIEW_KEY_RE = re.compile(r"^review-(\d+)-(\d+)$")


class Refused(Exception):
    pass


class BadInput(Exception):
    pass


# ---------- store primitives ----------

def atomic_write(path, text):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def write_json(path, obj):
    atomic_write(path, json.dumps(obj, indent=2, sort_keys=True) + "\n")


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


@contextlib.contextmanager
def locked(store):
    os.makedirs(store, exist_ok=True)
    with open(os.path.join(store, ".lock"), "a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def one_line(v):
    return re.sub(r"[\t\r\n]+", " ", str(v))


def read_rows(store):
    path = os.path.join(store, "units.tsv")
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return rows
    for line in lines[1:]:
        if not line:
            continue
        vals = line.split("\t")
        vals += [""] * (len(COLUMNS) - len(vals))
        row = dict(zip(COLUMNS, vals))
        row["attempt"] = int(row["attempt"] or 0)
        rows.append(row)
    return rows


def write_rows(store, rows):
    out = ["\t".join(COLUMNS)]
    for r in rows:
        out.append("\t".join(one_line(r.get(c, "")) for c in COLUMNS))
    atomic_write(os.path.join(store, "units.tsv"), "\n".join(out) + "\n")


def split_list(v):
    return [x for x in v.split(",") if x] if v else []


def load_config(store):
    cfg = read_json(os.path.join(store, "config.json"))
    if cfg is None:
        raise BadInput("store %s is not initialized; run init first" % store)
    return cfg


def load_units(store):
    return {u["id"]: u for u in read_json(os.path.join(store, "units.json"), [])}


def find_row(rows, uid):
    for r in rows:
        if r["id"] == uid:
            return r
    raise BadInput("unknown unit %s" % uid)


# ---------- git and process helpers ----------

def git(path, *args):
    p = subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def branch_head(cfg, branch):
    rc, out, _ = git(cfg["repo"], "rev-parse", "--verify", "-q", "refs/heads/" + branch)
    return out if rc == 0 else ""


def tree_dirty(worktree):
    if not worktree or not os.path.isdir(worktree):
        return "worktree %s is missing" % worktree
    rc, out, err = git(worktree, "status", "--porcelain")
    if rc != 0:
        return "git status failed in %s: %s" % (worktree, err)
    return "worktree %s has uncommitted changes" % worktree if out else ""


def is_ancestor(cfg, sha, ref):
    rc, _, _ = git(cfg["repo"], "merge-base", "--is-ancestor", sha, ref)
    return rc == 0


def pid_alive(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def real(path):
    return os.path.realpath(path) if path else ""


def freshness(cfg, row, head):
    """Why a clean result at head is no longer accepted, or '' when it still holds."""
    live = branch_head(cfg, row["branch"])
    if not head:
        return "workflow reported no head"
    if live != head:
        return "branch %s is at %s, reviewed head is %s" % (row["branch"], live[:12] or "(missing)", head[:12])
    return tree_dirty(row["worktree"])


# ---------- validation and import ----------

def validate_units(data):
    if not isinstance(data, list):
        raise BadInput("units file must be a JSON array")
    seen = set()
    for i, u in enumerate(data):
        where = "unit %d" % i
        if not isinstance(u, dict):
            raise BadInput("%s is not an object" % where)
        uid = u.get("id")
        if not isinstance(uid, str) or not ID_RE.match(uid):
            raise BadInput("%s: id must match %s (it names files and worktrees)" % (where, ID_RE.pattern))
        where = "unit %s" % uid
        if uid in seen:
            raise BadInput("%s: duplicate id" % where)
        seen.add(uid)
        if not isinstance(u.get("title"), str) or not u["title"].strip():
            raise BadInput("%s: title is required" % where)
        p = u.get("priority")
        if p is not None and (not isinstance(p, int) or isinstance(p, bool) or not 0 <= p <= 4):
            raise BadInput("%s: priority must be an integer 0..4" % where)
        for key in ("blockedBy", "paths", "claimedBy"):
            v = u.get(key)
            if v is not None and (not isinstance(v, list) or not all(isinstance(x, str) and x for x in v)):
                raise BadInput("%s: %s must be a list of non-empty strings" % (where, key))
        for dep in u.get("blockedBy") or []:
            if dep == uid:
                raise BadInput("%s: depends on itself" % where)
            if not ID_RE.match(dep):
                raise BadInput("%s: dependency %r is not a valid id" % (where, dep))
        for g in u.get("paths") or []:
            if re.search(r"[,\t\r\n]", g):
                raise BadInput("%s: path %r may not contain a comma, tab, or newline" % (where, g))
        for key in ("branch", "url", "body", "gate"):
            v = u.get(key)
            if v is not None and not isinstance(v, str):
                raise BadInput("%s: %s must be a string" % (where, key))
        b = u.get("branch")
        if b is not None and (not b or re.search(r"[\s,]", b)):
            raise BadInput("%s: branch %r is not usable" % (where, b))
        e = u.get("effort")
        if e is not None and e not in EFFORTS:
            raise BadInput("%s: effort must be one of %s" % (where, ", ".join(sorted(EFFORTS))))


def cmd_import(store, a):
    try:
        with open(a.file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise BadInput("cannot read %s: %s" % (a.file, e))
    validate_units(data)
    with locked(store):
        cfg = load_config(store)
        units = load_units(store)
        for u in data:
            units[u["id"]] = u
        rows = read_rows(store)
        by_id = {r["id"]: r for r in rows}
        for u in data:
            r = by_id.get(u["id"])
            if r is None:
                r = {c: "" for c in COLUMNS}
                r.update(id=u["id"], state="queued", attempt=0)
                rows.append(r)
                by_id[u["id"]] = r
            r["deps"] = ",".join(u.get("blockedBy") or [])
            r["paths"] = ",".join(u.get("paths") or [])
            r["branch"] = u.get("branch") or "graph/" + u["id"]
            r["effort"] = u.get("effort") or cfg["effort"]
            r["claim"] = " | ".join(one_line(c) for c in u.get("claimedBy") or [])
        for r in rows:
            unknown = [d for d in split_list(r["deps"]) if d not in by_id]
            was_unknown = r["state"] == "blocked" and r["reason"].startswith("unknown dependency")
            if unknown and (r["state"] == "queued" or was_unknown):
                r["state"], r["reason"] = "blocked", "unknown dependency " + unknown[0]
            elif not unknown and was_unknown:
                r["state"], r["reason"] = "queued", ""
        write_json(os.path.join(store, "units.json"), list(units.values()))
        write_rows(store, rows)
    print("imported %d units; store has %d" % (len(data), len(rows)))


# ---------- init ----------

STANDING_HEADER = """# Standing orders

1. Never rewrite history, discard uncommitted work, delete a worktree or branch, or act outside this machine (push, PRs, messages) without an authority line below.
2. One writer per unit: a unit with a live attempt, a claim, or unknown ownership is never launched again; reconcile decides from durable evidence.
3. Relaunch after a restart reuses the attempt's stored args file unchanged.
"""


def cmd_init(store, a):
    if a.effort not in EFFORTS:
        raise BadInput("effort must be one of %s" % ", ".join(sorted(EFFORTS)))
    if a.max_attempts < 1:
        raise BadInput("--max-attempts must be at least 1")
    repo = os.path.abspath(a.repo)
    rc, _, err = git(repo, "rev-parse", "--show-toplevel")
    if rc != 0:
        raise BadInput("%s is not a git checkout: %s" % (repo, err))
    rc, _, err = git(repo, "rev-parse", "--verify", "-q", a.base + "^{commit}")
    if rc != 0:
        raise BadInput("base %s does not resolve in %s" % (a.base, repo))
    cfg = {"repo": repo, "base": a.base, "worktrees": os.path.abspath(a.worktrees), "effort": a.effort,
           "max_attempts": a.max_attempts, "gate": a.gate}
    with locked(store):
        path = os.path.join(store, "config.json")
        old = read_json(path)
        if old is not None and old != cfg:
            raise Refused("store already initialized with a different config: %s" % json.dumps(old, sort_keys=True))
        if old is None:
            write_json(path, cfg)
        spath = os.path.join(store, "standing.md")
        try:
            with open(spath, encoding="utf-8") as f:
                standing = f.read()
        except FileNotFoundError:
            standing = STANDING_HEADER
        if a.grant:
            n = len(re.findall(r"^\d+\. ", standing, re.M)) + 1
            day = datetime.date.today().isoformat()
            standing += "%d. Authority granted by the user on %s, verbatim: %s\n" % (n, day, json.dumps(a.grant))
        if a.grant or not os.path.exists(spath):
            atomic_write(spath, standing)
    print("initialized %s" % store)


# ---------- scheduling ----------

def prefix(glob):
    return re.split(r"[*?\[]", glob, maxsplit=1)[0]


def overlaps(a_paths, b_paths):
    for a in a_paths:
        for b in b_paths:
            pa, pb = prefix(a), prefix(b)
            if pa.startswith(pb) or pb.startswith(pa):
                return True
    return False


def ineligible(cfg, row, rows_by_id):
    """Why row cannot launch regardless of what else runs, or ''."""
    st = row["state"]
    if st in RETRYABLE:
        if row["attempt"] >= cfg["max_attempts"]:
            return "attempt %d of %d used" % (row["attempt"], cfg["max_attempts"])
    elif st != "queued":
        return "state is %s" % st
    if row["claim"]:
        return "claimed: " + row["claim"]
    for dep in split_list(row["deps"]):
        d = rows_by_id.get(dep)
        if d is None:
            return "unknown dependency " + dep
        if d["state"] != "merged":
            return "dependency %s is %s, not merged" % (dep, d["state"])
        if d["head"] and not is_ancestor(cfg, d["head"], cfg["base"]):
            return "dependency %s head %s is not in %s" % (dep, d["head"][:12], cfg["base"])
    return ""


def plan(cfg, rows, units, window):
    """Launchable ids in priority order, and a reason for each unit left out."""
    by_id = {r["id"]: r for r in rows}
    active = [r for r in rows if r["state"] in LIVE]
    holding = active + [r for r in rows if r["state"] in ACCEPTED_UNMERGED]
    exclusive_active = any(not split_list(r["paths"]) for r in active)
    order = {r["id"]: i for i, r in enumerate(rows)}

    def key(r):
        p = (units.get(r["id"]) or {}).get("priority")
        return (p if p in (1, 2, 3, 4) else 5, order[r["id"]])

    picked, why = [], {}
    slots = window - len(active)
    for r in sorted(rows, key=key):
        reason = ineligible(cfg, r, by_id)
        paths = split_list(r["paths"])
        if not reason:
            if exclusive_active:
                reason = "a unit without paths is active"
            elif not paths and (active or picked):
                reason = "no paths: runs only when nothing else is active"
            elif picked and not split_list(picked[0]["paths"]):
                reason = "a unit without paths was picked first"
            else:
                for o in holding + picked:
                    if split_list(o["paths"]) and overlaps(paths, split_list(o["paths"])):
                        reason = "paths overlap %s (%s)" % (o["id"], o["state"] if o in holding else "picked")
                        break
        if not reason and len(picked) >= slots:
            reason = "window full"
        if reason:
            why[r["id"]] = reason
        else:
            picked.append(r)
    return [r["id"] for r in picked], why


def cmd_next(store, a):
    with locked(store):
        cfg = load_config(store)
        ids, _ = plan(cfg, read_rows(store), load_units(store), a.max)
    if a.json:
        print(json.dumps(ids))
    else:
        for i in ids:
            print(i)


# ---------- launch ----------

def render_brief(cfg, row, unit, prev_state, prev_reason):
    lines = ["# %s" % unit.get("title", row["id"]), "", "Unit: %s" % row["id"]]
    if unit.get("url"):
        lines.append("URL: %s" % unit["url"])
    lines += ["", "## Acceptance", "", (unit.get("body") or "").strip() or "Deliver what the title states.", "",
              "## Process", "",
              "These notes describe how to work. They are not acceptance criteria.", "",
              "- Work in %s on branch %s. Commit on this branch with new commits only." % (row["worktree"], row["branch"])]
    if row["paths"]:
        lines.append("- Expected paths: %s. Say so in your summary if the change needs others." % ", ".join(split_list(row["paths"])))
    if row["attempt"] > 1:
        lines.append("- This is attempt %d. The previous attempt ended `%s`%s. Read `git log %s..HEAD` before editing."
                     % (row["attempt"], prev_state, (": " + prev_reason) if prev_reason else "", cfg["base"]))
    return "\n".join(lines) + "\n"


def prepare_worktree(cfg, row):
    """Create or adopt the unit worktree; return a blocking reason or ''."""
    wt, branch = row["worktree"], row["branch"]
    if not os.path.lexists(wt):
        os.makedirs(os.path.dirname(wt), exist_ok=True)
        rc, _, err = git(cfg["repo"], "worktree", "add", "-q", "-b", branch, wt, cfg["base"])
        return "" if rc == 0 else "git worktree add failed: %s" % err
    rc, top, _ = git(wt, "rev-parse", "--show-toplevel")
    if rc != 0 or real(top) != real(wt):
        return "%s exists and is not a worktree root" % wt
    _, listing, _ = git(cfg["repo"], "worktree", "list", "--porcelain")
    known = {real(l[len("worktree "):]) for l in listing.splitlines() if l.startswith("worktree ")}
    if real(wt) not in known:
        return "%s is not a worktree of %s" % (wt, cfg["repo"])
    rc, cur, _ = git(wt, "symbolic-ref", "--short", "-q", "HEAD")
    if rc != 0 or cur != branch:
        return "%s is on %s, expected branch %s" % (wt, cur or "a detached HEAD", branch)
    return tree_dirty(wt)


def cmd_launch(store, a):
    with locked(store):
        cfg = load_config(store)
        rows, units = read_rows(store), load_units(store)
        row = find_row(rows, a.id)
        ids, why = plan(cfg, rows, units, 10 ** 9 if a.force_window else a.max)
        if a.id not in ids:
            raise Refused("%s is not launchable: %s" % (a.id, why.get(a.id, "not selected")))
        prev_state, prev_reason = row["state"], row["reason"]
        row.update(state="launching", attempt=row["attempt"] + 1, run="", start_head="", head="", reason="",
                   worktree=os.path.join(cfg["worktrees"], row["id"]))
        write_rows(store, rows)
        tag = "%s-%d" % (row["id"], row["attempt"])

        def block(reason):
            row.update(state="blocked", reason=reason)
            write_rows(store, rows)
            print(json.dumps({"id": row["id"], "attempt": row["attempt"], "state": "blocked", "reason": reason}))
            return 3

        reason = prepare_worktree(cfg, row)
        if reason:
            return block(reason)
        _, row["start_head"], _ = git(row["worktree"], "rev-parse", "HEAD")
        brief = os.path.join(store, "briefs", tag + ".md")
        atomic_write(brief, render_brief(cfg, row, units.get(row["id"], {}), prev_state, prev_reason))
        gate = units.get(row["id"], {}).get("gate") or cfg.get("gate")
        if not gate:
            return block("no gate: pass --gate to init or set gate on the unit")
        p = subprocess.run(["bash", ARGS_SCRIPT, brief, gate, cfg["base"], row["effort"], row["worktree"]],
                           cwd=cfg["repo"], capture_output=True, text=True)
        if p.returncode != 0:
            return block("review-loop-args.sh failed: %s" % one_line(p.stderr.strip()))
        args = json.loads(p.stdout)
        args["label"] = row["id"]
        args_path = os.path.join(store, "args", tag + ".json")
        if os.path.exists(args_path):
            return block("%s already exists" % args_path)
        atomic_write(args_path, json.dumps(args, sort_keys=True) + "\n")
        write_rows(store, rows)
        if p.stderr.strip():
            sys.stderr.write(p.stderr)
        # launch.json is written last: reconcile treats its absence as a launch that never finished.
        spec = {"id": row["id"], "attempt": row["attempt"], "cwd": cfg["repo"], "args_path": args_path,
                "workflow": os.path.abspath(a.workflow)}
        write_json(os.path.join(store, "args", tag + ".launch.json"), spec)
        print(json.dumps(spec))
    return 0


# ---------- bind ----------

def check_attempt(row, attempt):
    if attempt != row["attempt"]:
        raise Refused("%s attempt %d is not the current attempt %d" % (row["id"], attempt, row["attempt"]))


def cmd_bind(store, a):
    if not re.match(r"^[A-Za-z0-9._-]+$", a.run_id):
        raise BadInput("run id %r is not valid" % a.run_id)
    with locked(store):
        load_config(store)
        rows = read_rows(store)
        row = find_row(rows, a.id)
        check_attempt(row, a.attempt)
        runs = split_list(row["run"])
        if row["state"] == "launching":
            runs = [a.run_id]
        elif row["state"] == "running":
            if a.run_id in runs:
                print("%s attempt %d already bound to %s" % (a.id, a.attempt, a.run_id))
                return 0
            runs.append(a.run_id)
        else:
            raise Refused("%s is %s; only a launching or running attempt can be bound" % (a.id, row["state"]))
        row.update(state="running", run=",".join(runs))
        write_rows(store, rows)
    print("%s attempt %d running as %s" % (a.id, a.attempt, a.run_id))
    return 0


# ---------- record ----------

def load_run_file(path):
    """Return (status, status_path) for a workflow status.json or workflow-receipt.json."""
    doc = read_json(path)
    if not isinstance(doc, dict):
        raise BadInput("%s is not a JSON object" % path)
    if "workflowRunId" in doc and "mode" not in doc:
        spath = os.path.join(os.path.dirname(os.path.abspath(path)), "status.json")
        status = read_json(spath)
        if not isinstance(status, dict):
            raise BadInput("%s is a workflow receipt; the return value lives in %s, which is missing" % (path, spath))
        if status.get("runId") != doc["workflowRunId"]:
            raise BadInput("%s belongs to run %s, not %s" % (spath, status.get("runId"), doc["workflowRunId"]))
        return status, spath
    if doc.get("mode") != "workflow":
        raise BadInput("%s is not a workflow status.json or workflow-receipt.json" % path)
    return doc, os.path.abspath(path)


def workflow_value(status):
    v = (status.get("workflow") or {}).get("value")
    return v if isinstance(v, dict) and v.get("state") in WORKFLOW_STATES else None


def build_receipt(cfg, row, status, args):
    value = workflow_value(status) or {}
    runs = value.get("runs") if isinstance(value.get("runs"), list) else []
    required = args.get("reviewers", 1)
    rounds = value.get("rounds") or 0
    reviewers = [{"key": r.get("key"), "run": r.get("runId"), "ok": bool(r.get("ok"))}
                 for r in runs if isinstance(r, dict) and REVIEW_KEY_RE.match(str(r.get("key")))]
    last = {r["key"]: r["ok"] for r in reviewers}
    missing = [k for k in ("review-%d-%d" % (rounds, i) for i in range(1, required + 1)) if not last.get(k)]
    non_blocking = value.get("nonBlocking") if isinstance(value.get("nonBlocking"), list) else []
    blocking = value.get("blocking") if isinstance(value.get("blocking"), list) else []
    return {
        "version": 1,
        "unit": row["id"],
        "attempt": row["attempt"],
        "run": status.get("runId"),
        "base": args.get("base"),
        "start_head": row["start_head"],
        "reviewed_head": value.get("head"),
        "workflow_state": value.get("state"),
        "runtime_state": status.get("state"),
        "rounds": rounds,
        "reviewers_required": required,
        "reviewers": reviewers,
        "reviewers_not_ok": missing,
        "blocking": len(blocking),
        "non_blocking": len(non_blocking),
        "downgraded": sum(1 for f in non_blocking if isinstance(f, dict) and f.get("downgraded")),
        "gate": args.get("gate"),
    }


def cmd_record(store, a):
    status, spath = load_run_file(a.file)
    run = status.get("runId")
    with locked(store):
        cfg = load_config(store)
        rows = read_rows(store)
        row = find_row(rows, a.id)
        check_attempt(row, a.attempt)
        tag = "%s-%d" % (row["id"], row["attempt"])
        rpath = os.path.join(store, "receipts", tag + ".json")
        prior = read_json(rpath)
        if prior is not None and prior.get("run") != run:
            raise Refused("%s attempt %d was recorded from run %s, not %s" % (a.id, a.attempt, prior.get("run"), run))
        if prior is not None and row["state"] != "running":
            print("%s attempt %d already recorded from run %s: %s" % (a.id, a.attempt, run, row["state"]))
            return 0
        if row["state"] != "running":
            raise Refused("%s is %s; bind the attempt before recording it" % (a.id, row["state"]))
        if run not in split_list(row["run"]):
            raise Refused("run %s is not bound to %s attempt %d" % (run, a.id, a.attempt))
        if status.get("state") not in RUNTIME_TERMINAL:
            raise BadInput("run %s is %s, not terminal; nothing to record yet" % (run, status.get("state")))
        args = read_json(os.path.join(store, "args", tag + ".json"), {})
        receipt = build_receipt(cfg, row, status, args)
        ws = receipt["workflow_state"]
        if ws is None:
            state, reason = "run-failed", "workflow %s without a return value" % status.get("state")
            head = branch_head(cfg, row["branch"])
        else:
            state, head = ws, receipt["reviewed_head"] or ""
            reason = {
                "clean": "",
                "unresolved": "%d blocking findings after %d rounds" % (receipt["blocking"], receipt["rounds"]),
                "gate-failed": "two coder runs in a row failed",
                "review-failed": "a reviewer failed or returned no structured findings",
                "blocked": "the coder needs a decision; read its summary",
            }[ws]
            if ws == "clean":
                if receipt["reviewers_not_ok"]:
                    reason = "required reviewers did not return ok: " + ", ".join(receipt["reviewers_not_ok"])
                else:
                    reason = freshness(cfg, row, head)
                if reason:
                    state = "stale"
        if state in RETRYABLE and row["attempt"] >= cfg["max_attempts"]:
            reason = "%s at attempt %d of %d: %s" % (state, row["attempt"], cfg["max_attempts"], reason)
            state = "parked"
        receipt.update(file=spath, unit_state=state, reason=reason,
                       recorded_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
        write_json(rpath, receipt)
        row.update(state=state, head=head, reason=reason)
        write_rows(store, rows)
    print("%s attempt %d: %s%s" % (a.id, a.attempt, state, (" (" + reason + ")") if reason else ""))
    return 0


# ---------- status ----------

def cmd_status(store, a):
    with locked(store):
        cfg = load_config(store)
        rows = read_rows(store)
    out = []
    for r in rows:
        state, reason = r["state"], r["reason"]
        if state == "clean":
            stale = freshness(cfg, r, r["head"])
            if stale:
                state, reason = "stale", stale
        out.append({"id": r["id"], "state": state, "attempt": r["attempt"], "branch": r["branch"],
                    "head": r["head"], "run": split_list(r["run"]), "reason": reason})
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        for u in out:
            print("\t".join([u["id"], u["state"], str(u["attempt"]), u["reason"]]))


# ---------- reconcile ----------

def run_status(runs_dir, run):
    return read_json(os.path.join(runs_dir, run, "status.json"))


def unit_children(runs_dir, worktree, owned_runs):
    """Child runs that write in this worktree or belong to one of its workflows."""
    found = []
    wt = real(worktree)
    try:
        names = sorted(os.listdir(runs_dir))
    except FileNotFoundError:
        return found
    for name in names:
        st = read_json(os.path.join(runs_dir, name, "status.json"))
        if not isinstance(st, dict) or st.get("mode") == "workflow":
            continue
        parent = st.get("parentWorkflowRunId")
        if (st.get("cwd") and real(st["cwd"]) == wt) or parent in owned_runs:
            alive = st.get("state") not in RUNTIME_TERMINAL and pid_alive(st.get("pid"))
            found.append({"run": st.get("runId", name), "parent": parent, "state": st.get("state"),
                          "pid": st.get("pid"), "alive": alive})
    return found


def decide(cfg, store, row, runs_dir):
    tag = "%s-%d" % (row["id"], row["attempt"])
    args_path = os.path.join(store, "args", tag + ".json")
    runs = split_list(row["run"])
    kids = unit_children(runs_dir, row["worktree"], set(runs))
    live = [k for k in kids if k["alive"]]
    foreign = [k for k in live if k["parent"] not in runs]
    res = {"id": row["id"], "attempt": row["attempt"], "state": row["state"], "runs": runs,
           "live_children": [k["run"] for k in live]}

    def act(action, reason, **extra):
        res.update(action=action, reason=reason, **extra)
        return res

    spec = read_json(os.path.join(store, "args", tag + ".launch.json"), {})
    relaunch = {"args_path": args_path, "workflow": spec.get("workflow", DEFAULT_WORKFLOW), "cwd": cfg["repo"]}
    if foreign:
        return act("hold", "live child %s writes in %s and is not owned by this attempt"
                   % (foreign[0]["run"], row["worktree"]))
    commits = ""
    if row["start_head"]:
        _, commits, _ = git(row["worktree"], "rev-list", "--count", row["start_head"] + "..HEAD")
    if row["state"] == "launching":
        if not os.path.exists(os.path.join(store, "args", tag + ".launch.json")):
            return act("hold", "launch did not finish (no launch.json), so nothing was dispatched. "
                       "Use set %s parked, then set %s queued" % (row["id"], row["id"]))
        if commits not in ("", "0"):
            return act("hold", "no run bound but %s commits since start head %s" % (commits, row["start_head"][:12]))
        return act("relaunch-same-args", "intent written, no run bound, no live writer", **relaunch)
    cur = runs[-1] if runs else ""
    st = run_status(runs_dir, cur) if cur else None
    if not isinstance(st, dict):
        if live:
            return act("relaunch-same-args", "workflow %s missing; child %s still alive" % (cur, live[0]["run"]), **relaunch)
        return act("hold", "workflow %s has no status.json and no live writer" % cur)
    wstate = st.get("state")
    if wstate not in RUNTIME_TERMINAL and pid_alive(st.get("pid")):
        return act("wait", "workflow %s is %s" % (cur, wstate))
    path = os.path.join(runs_dir, cur, "status.json")
    if workflow_value(st) is not None:
        if wstate not in RUNTIME_TERMINAL:
            return act("hold", "workflow %s has a value but is %s with a dead pid" % (cur, wstate))
        return act("record", "workflow %s %s with a return value" % (cur, wstate), file=path)
    if live:
        return act("relaunch-same-args", "workflow %s %s; child %s still alive" % (cur, wstate, live[0]["run"]), **relaunch)
    if wstate not in RUNTIME_TERMINAL:
        return act("hold", "workflow %s is %s but its process is gone and no writer is alive" % (cur, wstate))
    return act("retry", "workflow %s %s without a return value; no live writer. Record the file, then launch"
               % (cur, wstate), file=path)


def cmd_reconcile(store, a):
    with locked(store):
        cfg = load_config(store)
        rows = read_rows(store)
    out = [decide(cfg, store, r, a.runs_dir) for r in rows if r["state"] in LIVE]
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        for d in out:
            print("\t".join([d["id"], d["action"], d["reason"]]))


# ---------- set ----------

def cmd_set(store, a):
    if a.state not in SET_TARGETS:
        raise BadInput("set accepts only %s" % ", ".join(sorted(SET_TARGETS)))
    with locked(store):
        load_config(store)
        rows = read_rows(store)
        row = find_row(rows, a.id)
        if row["state"] in LIVE and a.state != "parked":
            raise Refused("%s has a live attempt (%s); only parked is allowed" % (a.id, row["state"]))
        row.update(state=a.state, reason=a.reason)
        write_rows(store, rows)
    print("%s: %s" % (a.id, a.state))


# ---------- main ----------

def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--store", default=argparse.SUPPRESS, help="graph store directory")
    p = argparse.ArgumentParser(prog="graph.py", description=__doc__.split("\n")[0])
    p.add_argument("--store", help="graph store directory")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", parents=[common])
    s.add_argument("--repo", required=True)
    s.add_argument("--base", required=True)
    s.add_argument("--worktrees", required=True)
    s.add_argument("--effort", default="standard")
    s.add_argument("--gate", default="")
    s.add_argument("--max-attempts", type=int, default=3)
    s.add_argument("--grant")

    s = sub.add_parser("import", parents=[common])
    s.add_argument("file")

    s = sub.add_parser("next", parents=[common])
    s.add_argument("--max", type=int, default=1)
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("launch", parents=[common])
    s.add_argument("id")
    s.add_argument("--max", type=int, default=1)
    s.add_argument("--force-window", action="store_true")
    s.add_argument("--workflow", default=DEFAULT_WORKFLOW)

    s = sub.add_parser("bind", parents=[common])
    s.add_argument("id")
    s.add_argument("attempt", type=int)
    s.add_argument("run_id")

    s = sub.add_parser("record", parents=[common])
    s.add_argument("id")
    s.add_argument("attempt", type=int)
    s.add_argument("file")

    s = sub.add_parser("status", parents=[common])
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("reconcile", parents=[common])
    s.add_argument("--runs-dir", required=True)
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("set", parents=[common])
    s.add_argument("id")
    s.add_argument("state")
    s.add_argument("--reason", required=True)
    return p


COMMANDS = {"init": cmd_init, "import": cmd_import, "next": cmd_next, "launch": cmd_launch, "bind": cmd_bind,
            "record": cmd_record, "status": cmd_status, "reconcile": cmd_reconcile, "set": cmd_set}


def main(argv=None):
    a = parser().parse_args(argv)
    if not a.store:
        print("--store DIR is required", file=sys.stderr)
        return 2
    store = os.path.abspath(a.store)
    try:
        return COMMANDS[a.cmd](store, a) or 0
    except BadInput as e:
        print("graph: %s" % e, file=sys.stderr)
        return 2
    except Refused as e:
        print("graph: refused: %s" % e, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
