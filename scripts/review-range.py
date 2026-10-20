#!/usr/bin/env python3
"""Track which commits on a branch have passed review, so each review covers only new commits.

usage:
  review-range.py record <task-dir> <trunk> <base> <head> <source> [--cwd DIR]
  review-range.py base   <task-dir> <trunk> [--cwd DIR]
  review-range.py args   <task-dir> <trunk> <effort> <intent> [--cwd DIR] [--label LABEL]

record  appends to <task-dir>/reviewed.tsv that a review read `git diff <base>...<head>` and left
        nothing it raised open, with a hash of that exact diff. <source> names the review, such
        as review-loop or pre-push. When the ledger then covers <trunk>'s merge-base through
        <head>, it also records that whole range, so a later rebase can match it.
base    prints the commit to review from: the furthest commit on HEAD's first-parent chain that
        the ledger covers, starting at the merge-base of <trunk> and HEAD. A recorded range
        covers forward from the current point when its base is at or before that point and its
        head is on the branch. After a rebase the recorded SHAs are gone, so a commit is also
        covered when the diff from the current point to it is byte-identical to a recorded
        diff, or empty. Exit 3 when HEAD is covered (nothing new to review).
args    prints the args JSON for workflows/review-fanout.js over the uncovered commits, pinned to
        the current HEAD, with the interrogate rubric and the effort's reviewers: standard runs
        the reviewer role, exhaustive adds a second on the review2 slot. Prints the matching
        record command on stderr. Exit 3 when there is nothing to review: quick effort, or HEAD
        covered.

The diff hash includes full blob ids, so a rebase keeps coverage only when every file the
branch touches is byte-identical before and after its change, as after `gh stack rebase` onto a
squash-merged parent. Any trunk change to a touched file sends the branch back to review. For a
stacked PR, pass the PR's base branch as <trunk>: each branch has its own task dir and ledger.
Every git failure is an error (exit 2), never coverage.
"""
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = "reviewed.tsv"
NOTHING = 3
SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
# Pin every option and config that changes diff output, so the hash reflects the trees alone and
# no setting (ignored submodules, a relative diff, an external or textconv driver) hides a change.
DIFF = ["-c", "diff.ignoreSubmodules=none", "-c", "diff.relative=false", "-c", "diff.noprefix=false",
        "-c", "diff.mnemonicPrefix=false", "-c", "core.quotePath=true",
        "diff", "--binary", "--full-index", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames",
        "--ignore-submodules=none", "--no-relative", "--src-prefix=a/", "--dst-prefix=b/",
        "--diff-algorithm=myers", "--unified=3"]
EMPTY = hashlib.sha256(b"").hexdigest()


class Bad(Exception):
    pass


def git(cwd, *args, check=True):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    if check and r.returncode:
        raise Bad(f"git {' '.join(args)} failed in {cwd}: {r.stderr.strip()}")
    return r


def sha(cwd, ref):
    return git(cwd, "rev-parse", "--verify", "--quiet", ref + "^{commit}", check=False).stdout.strip()


def is_ancestor(cwd, a, b):
    r = git(cwd, "merge-base", "--is-ancestor", a, b, check=False)
    if r.returncode not in (0, 1):
        raise Bad(f"git merge-base --is-ancestor {a} {b} failed in {cwd}: {r.stderr.strip()}")
    return r.returncode == 0


def diff_hash(cwd, a, b):
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIFF_OPTS", "GIT_EXTERNAL_DIFF")}
    r = subprocess.run(["git", "-C", cwd, *DIFF, a, b, "--"], capture_output=True, env=env)
    if r.returncode:
        raise Bad(f"git diff {a} {b} failed in {cwd}: {r.stderr.decode(errors='replace').strip()}")
    return hashlib.sha256(r.stdout).hexdigest()


def ledger(task_dir):
    """Recorded (base, head, diff hash) rows; rows in any other shape are ignored."""
    rows = []
    try:
        with open(os.path.join(task_dir, LEDGER)) as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if (len(parts) == 4 and SHA_RE.match(parts[0]) and SHA_RE.match(parts[1])
                        and re.match(r"^[0-9a-f]{64}$", parts[2])):
                    rows.append(tuple(parts[:3]))
    except FileNotFoundError:
        pass
    return rows


def merge_base(cwd, trunk, tip):
    r = git(cwd, "merge-base", trunk, tip, check=False)
    if r.returncode:
        raise Bad(f"cannot resolve the merge-base of {trunk} and {tip} in {cwd}")
    return r.stdout.strip()


def coverage(task_dir, trunk, tip, cwd):
    """(furthest covered commit on tip's first-parent chain, merge-base)."""
    mb = merge_base(cwd, trunk, tip)
    rows = ledger(task_dir)
    hashes = {h for _, _, h in rows}
    cur = mb
    while rows and cur != tip:
        nxt = next((h for b, h, _ in rows if h != cur and is_ancestor(cwd, b, cur)
                    and is_ancestor(cwd, cur, h) and is_ancestor(cwd, h, tip)), None)
        if nxt is None:
            for x in git(cwd, "rev-list", "--first-parent", "--ancestry-path", f"{cur}..{tip}").stdout.split():
                d = diff_hash(cwd, cur, x)
                if d == EMPTY or d in hashes:
                    nxt = x
                    break
        if nxt is None:
            break
        cur = nxt
    return cur, mb


def append(task_dir, base, head, digest, source):
    os.makedirs(task_dir, exist_ok=True)
    with open(os.path.join(task_dir, LEDGER), "a") as f:
        f.write(f"{base}\t{head}\t{digest}\t{source}\n")


def record(task_dir, trunk, base, head, source, cwd):
    b, h = sha(cwd, base), sha(cwd, head)
    if not b or not h:
        raise Bad(f"cannot resolve {base if not b else head} in {cwd}")
    if "\t" in source or "\n" in source:
        raise Bad("source must not contain tabs or newlines")
    if not is_ancestor(cwd, b, h):
        raise Bad(f"{base} is not an ancestor of {head}")
    mb = merge_base(cwd, trunk, h)
    append(task_dir, b, h, diff_hash(cwd, b, h), source)
    covered, _ = coverage(task_dir, trunk, h, cwd)
    if covered == h and b != mb:
        append(task_dir, mb, h, diff_hash(cwd, mb, h), source)
    print(f"recorded {b[:12]}..{h[:12]} ({source})" + ("" if covered == h else
          f"; {trunk}'s merge-base through {h[:12]} is not yet covered"))


def review_base(task_dir, trunk, cwd):
    """(base sha, head sha, merge-base sha)."""
    head = sha(cwd, "HEAD")
    if not head:
        raise Bad(f"cannot resolve HEAD in {cwd}")
    base, mb = coverage(task_dir, trunk, head, cwd)
    return base, head, mb


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
    base, head, mb = review_base(task_dir, trunk, cwd)
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
    pre_read = (f"Pre-read: run `python3 {os.path.join(ROOT, 'scripts', 'review-pre-read.py')} {base} {head}` in your cwd "
                "and read its output before the diff. It is a map of the change: removed or renamed names with their "
                "surviving references, related tests, and the diff. Verify a lead there from the code; do not report "
                "it from the list.")
    if base != mb:
        print(f"skipping reviewed commits up to {base[:12]}", file=sys.stderr)
    args = {
        "task": f"Apply the rubric at {rubric}/rubric.md and {rubric}/code-quality-review.md.",
        "targets": [{"key": "branch", "cwd": top, "base": base, "head": head, "task": pre_read + "\n\n" + intent.strip() + "\n\n" + scope}],
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
    want = {"record": 6, "base": 3, "args": 5}
    if not pos or pos[0] not in want or len(pos) != want[pos[0]]:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    try:
        if pos[0] == "record":
            record(pos[1], pos[2], pos[3], pos[4], pos[5], cwd)
            return 0
        if pos[0] == "base":
            base, head, _ = review_base(pos[1], pos[2], cwd)
            print(base)
            return NOTHING if base == head else 0
        built = build_args(pos[1], pos[2], pos[3], pos[4], cwd, opts["--label"])
        if built is None:
            return NOTHING
        args, head = built
        print(json.dumps(args))
        cmd = [os.path.abspath(__file__), "record", os.path.abspath(pos[1]), pos[2], args["targets"][0]["base"],
               head, opts["--label"], "--cwd", cwd]
        print("after the review, once nothing it raised is open, run: " + shlex.join(cmd), file=sys.stderr)
        return 0
    except Bad as e:
        print(f"review-range.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
