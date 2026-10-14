#!/usr/bin/env python3
"""Track which commits on a branch have passed review, so each review covers only new commits.

usage:
  review-range.py record <task-dir> <base> <head> <source> [--cwd DIR]
  review-range.py base   <task-dir> <trunk> [--cwd DIR]
  review-range.py args   <task-dir> <trunk> <effort> <intent> [--cwd DIR] [--label LABEL]

record  appends each commit in <base>..<head> to <task-dir>/reviewed.tsv with its patch-id: the
        review read that range and nothing it raised is left open. <source> names the review,
        such as review-loop or pre-push.
base    prints the commit to review from. It walks the first-parent commits from the merge-base
        of <trunk> and HEAD, oldest first, and stops at the first one not covered; the review
        starts at that commit's parent. A commit is covered when its SHA or patch-id is in the
        ledger, when its diff is empty, or when it merges commits already in <trunk> without
        resolving a conflict. Exit 3 when every commit is covered (nothing new to review).
args    prints the args JSON for workflows/review-fanout.js over the unreviewed commits, with the
        interrogate rubric and the effort's reviewers: standard runs the reviewer role,
        exhaustive adds a second on the review2 slot. Exit 3 when there is nothing to review:
        quick effort, or every commit covered.

A patch-id hashes a commit's diff, so a rebase that replays a commit without conflicts keeps
its review, and a commit whose diff changed while resolving a conflict is reviewed again. For a
stacked PR, pass the PR's base branch as <trunk>: each branch has its own task dir and ledger.
Exit 2 on bad input.
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
    """(reviewed patch-ids, reviewed SHAs)."""
    pids, shas = set(), set()
    try:
        with open(os.path.join(task_dir, LEDGER)) as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2:
                    if parts[0] != "-":
                        pids.add(parts[0])
                    shas.add(parts[1])
    except FileNotFoundError:
        pass
    return pids, shas


def parents(cwd, c):
    return git(cwd, "rev-list", "--parents", "-n", "1", c).stdout.split()[1:]


def patch_id(cwd, c):
    """The commit's stable patch-id, or None for a merge or an empty diff."""
    if len(parents(cwd, c)) > 1:
        return None
    diff = git(cwd, "show", "--format=", "--no-color", "--no-ext-diff", c).stdout
    if not diff.strip():
        return None
    r = subprocess.run(["git", "-C", cwd, "patch-id", "--stable"], input=diff, capture_output=True, text=True)
    out = r.stdout.split()
    return out[0] if out else None


def record(task_dir, base, head, source, cwd):
    b, h = sha(cwd, base), sha(cwd, head)
    if not b or not h:
        raise Bad(f"cannot resolve {base if not b else head} in {cwd}")
    if not is_ancestor(cwd, b, h):
        raise Bad(f"{base} is not an ancestor of {head}")
    commits = git(cwd, "rev-list", "--reverse", f"{b}..{h}").stdout.split()
    os.makedirs(task_dir, exist_ok=True)
    with open(os.path.join(task_dir, LEDGER), "a") as f:
        for c in commits:
            f.write(f"{patch_id(cwd, c) or '-'}\t{c}\t{source}\n")
    print(f"recorded {len(commits)} commit(s) in {b[:12]}..{h[:12]} ({source})")


def covered(cwd, c, trunk, pids, shas):
    if c in shas:
        return True
    ps = parents(cwd, c)
    if len(ps) > 1:
        # A clean merge of trunk adds only reviewed or upstream code; `--cc` prints only the
        # hunks a conflict resolution or an evil merge changed.
        return (all(is_ancestor(cwd, p, trunk) for p in ps[1:])
                and not git(cwd, "show", "--cc", "--format=", "--no-color", c).stdout.strip())
    pid = patch_id(cwd, c)
    return pid is None or pid in pids


def review_base(task_dir, trunk, cwd):
    """(base sha, head sha, merge-base sha, commits skipped as covered)."""
    head = sha(cwd, "HEAD")
    r = git(cwd, "merge-base", trunk, "HEAD", check=False)
    if r.returncode or not head:
        raise Bad(f"cannot resolve the merge-base of {trunk} and HEAD in {cwd}")
    mb = r.stdout.strip()
    trunk_sha = sha(cwd, trunk)
    pids, shas = ledger(task_dir)
    base, skipped = mb, 0
    for c in git(cwd, "rev-list", "--reverse", "--first-parent", f"{mb}..{head}").stdout.split():
        if not covered(cwd, c, trunk_sha, pids, shas):
            break
        base, skipped = c, skipped + 1
    return base, head, mb, skipped


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
             f"{mb[:12]}, already passed review or carry no new change." if base != mb else "Review the whole branch.")
    rubric = os.path.join(ROOT, "skills", "interrogate", "references")
    if used:
        print(f"skipping {used} covered commit(s) up to {base[:12]}", file=sys.stderr)
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
