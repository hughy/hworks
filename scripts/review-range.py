#!/usr/bin/env python3
"""Track which commits on a branch have passed review, so each review covers only new commits.

usage:
  review-range.py record <task-dir> <base> <head> <source> [--cwd DIR]
  review-range.py base   <task-dir> <trunk> [--cwd DIR]
  review-range.py args   <task-dir> <trunk> <effort> <intent> [--cwd DIR] [--label LABEL]

record  appends one reviewed range to <task-dir>/reviewed.tsv: the review read <base>...<head>
        and nothing it raised is left open. <base> and <head> are refs or SHAs, stored as SHAs.
        <source> names the review, such as review-loop or pre-push.
base    prints the commit to review from: start at the merge-base of <trunk> and HEAD, then
        follow recorded ranges whose base is at or before the current point and whose head
        is an ancestor of HEAD, as far as they reach. Exit 3 when that is HEAD itself
        (nothing new to review).
args    prints the args JSON for workflows/review-fanout.js over the unreviewed range, with the
        interrogate rubric and the effort's reviewers: standard runs the reviewer role,
        exhaustive adds a second on the review2 slot. Exit 3 when there is nothing to review:
        quick effort, or HEAD already reviewed.

A rebase rewrites the recorded commits, so they stop being ancestors of HEAD and the next
review covers the whole branch again. Exit 2 on bad input.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = "reviewed.tsv"
NOTHING = 3


class Bad(Exception):
    pass


def git(cwd, *args, check=True):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    if check and r.returncode:
        raise Bad(f"git {' '.join(args)} failed in {cwd}: {r.stderr.strip()}")
    return r


def sha(cwd, ref):
    return git(cwd, "rev-parse", "--verify", "--quiet", ref + "^{commit}").stdout.strip()


def is_ancestor(cwd, a, b):
    return git(cwd, "merge-base", "--is-ancestor", a, b, check=False).returncode == 0


def ledger(task_dir):
    path = os.path.join(task_dir, LEDGER)
    rows = []
    try:
        with open(path) as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3:
                    rows.append({"base": parts[0], "head": parts[1], "source": parts[2]})
    except FileNotFoundError:
        pass
    return rows


def record(task_dir, base, head, source, cwd):
    b, h = sha(cwd, base), sha(cwd, head)
    if not b or not h:
        raise Bad(f"cannot resolve {base if not b else head} in {cwd}")
    if not is_ancestor(cwd, b, h):
        raise Bad(f"{base} is not an ancestor of {head}")
    os.makedirs(task_dir, exist_ok=True)
    with open(os.path.join(task_dir, LEDGER), "a") as f:
        f.write(f"{b}\t{h}\t{source}\n")
    print(f"recorded {b[:12]}..{h[:12]} ({source})")


def review_base(task_dir, trunk, cwd):
    """(base sha, head sha, merge-base sha, ranges used)."""
    head = sha(cwd, "HEAD")
    r = git(cwd, "merge-base", trunk, "HEAD", check=False)
    if r.returncode or not head:
        raise Bad(f"cannot resolve the merge-base of {trunk} and HEAD in {cwd}")
    mb = r.stdout.strip()
    cur, used = mb, []
    rows = [x for x in ledger(task_dir) if sha(cwd, x["head"]) == x["head"] and is_ancestor(cwd, x["head"], head)]
    while True:
        ahead = [x for x in rows if x["head"] != cur and is_ancestor(cwd, x["base"], cur)
                 and is_ancestor(cwd, cur, x["head"])]
        if not ahead:
            return cur, head, mb, used
        # Any range usable here stays usable once cur advances, so the order of steps
        # does not change where the walk ends.
        used.append(ahead[0])
        cur = ahead[0]["head"]


def models():
    session = ""
    if os.environ.get("PI_PROVIDER") and os.environ.get("PI_MODEL"):
        session = f"{os.environ['PI_PROVIDER']}/{os.environ['PI_MODEL']}"
    out = subprocess.run([os.path.join(ROOT, "scripts", "models.sh"), "show"], capture_output=True, text=True)
    if out.returncode:
        raise Bad(f"scripts/models.sh show failed: {out.stderr.strip()}")
    found = {}
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            found[parts[0]] = session if parts[1] == "(session" else parts[1]
    return found


def bare(model):
    for level in ("off", "minimal", "low", "medium", "high", "xhigh", "max"):
        if model.endswith(":" + level):
            return model[: -len(level) - 1]
    return model


def build_args(task_dir, trunk, effort, intent, cwd, label):
    if effort not in ("quick", "standard", "exhaustive"):
        raise Bad(f"effort must be quick, standard or exhaustive, got: {effort}")
    if not intent.strip():
        raise Bad("intent must be non-empty")
    if effort == "quick":
        print("quick effort runs no review; the gate and the grep still apply", file=sys.stderr)
        return None
    base, head, mb, used = review_base(task_dir, trunk, cwd)
    if base == head:
        print(f"HEAD {head[:12]} already passed review; nothing new to review", file=sys.stderr)
        return None
    top = git(cwd, "rev-parse", "--show-toplevel").stdout.strip()
    reviewers = [{"agent": "reviewer", "label": "reviewer"}]
    if effort == "exhaustive":
        m = models()
        r2, r1 = m.get("review2", ""), m.get("reviewer", "")
        second = {"agent": "reviewer", "label": "review2"}
        if r2:
            second["model"] = r2
        else:
            print("warning: review2 slot is the session model and PI_PROVIDER/PI_MODEL are unset; "
                  "the second reviewer runs on the reviewer model", file=sys.stderr)
        if bare(r2 or r1) == bare(r1):
            print(f"warning: review2 runs the reviewer model ({r1 or 'session model'}); both reviews run on one model",
                  file=sys.stderr)
        reviewers.append(second)
    scope = (f"Review only the commits after {base[:12]}: the commits before it, back to the merge-base "
             f"{mb[:12]}, already passed review." if base != mb else "Review the whole branch.")
    rubric = os.path.join(ROOT, "skills", "interrogate", "references")
    if used:
        print(f"skipping {len(used)} reviewed range(s) up to {base[:12]}", file=sys.stderr)
    args = {
        "task": f"Apply the rubric at {rubric}/rubric.md and {rubric}/code-quality-review.md.",
        "targets": [{"key": "branch", "cwd": top, "base": base, "task": intent.strip() + "\n\n" + scope}],
        "reviewers": reviewers,
        "label": label,
        "taskDir": os.path.abspath(task_dir),
    }
    return args, head


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    opts = {"--cwd": ".", "--label": "pre-push"}
    pos = []
    while argv:
        a = argv.pop(0)
        if a in opts:
            if not argv:
                print(f"{a} needs a value", file=sys.stderr)
                return 2
            opts[a] = argv.pop(0)
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            pos.append(a)
    cwd = os.path.abspath(opts["--cwd"])
    want = {"record": 5, "base": 3, "args": 5}
    if not pos or pos[0] not in want or len(pos) != want[pos[0]]:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    try:
        if pos[0] == "record":
            record(pos[1], pos[2], pos[3], pos[4], cwd)
            return 0
        if pos[0] == "base":
            base, head, _, _ = review_base(pos[1], pos[2], cwd)
            print(base)
            return NOTHING if base == head else 0
        built = build_args(pos[1], pos[2], pos[3], pos[4], cwd, opts["--label"])
        if built is None:
            return NOTHING
        args, head = built
        print(json.dumps(args))
        print(f"after the review, once its findings are fixed or dismissed, run: {sys.argv[0]} record "
              f"{pos[1]} {args['targets'][0]['base']} {head} {opts['--label']} --cwd {cwd}", file=sys.stderr)
        return 0
    except Bad as e:
        print(f"review-range.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
