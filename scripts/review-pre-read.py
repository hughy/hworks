#!/usr/bin/env python3
"""Print a map of a change for a reviewer to read before the diff.

usage: review-pre-read.py <base> <head> [--cwd DIR] [--out FILE] [--json]

Sections, in order:
  Changed files            git diff --name-status <base>...<head>
  Removed or renamed names identifiers on removed lines that appear on no added line, each with
                           its surviving references at <head> (git grep -n -w). Heuristic: a
                           surviving reference is a lead to check, not a defect. Capped at 40 names.
  Related tests            test files at <head> that mention a changed file's stem, and the changed
                           test files. Heuristic by path.
  Diff                     git diff <base>...<head>, cut after 4000 lines.

Writes to stdout, or to FILE with --out. Never modifies the repo. Every git failure exits 2.
"""
import json
import os
import re
import subprocess
import sys

MAX_NAMES = 40
MAX_HITS = 5
MAX_DIFF_LINES = 4000
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
DIFF = ["-c", "core.quotePath=true", "diff", "--no-color", "--no-ext-diff"]
# A removed line in a prose file is mostly words; only its backticked spans name code.
PROSE = {".md", ".markdown", ".txt", ".rst", ".adoc"}
CODE_SPAN = re.compile(r"`([^`]+)`")
STOP = set("""
and any are assert async await break case catch class const continue def del elif else except exec
false finally for from global import lambda nonlocal not pass print raise return true try while with
yield none self cls str int float bool list dict set tuple len range open isinstance super object
function var let new this typeof instanceof void delete throw switch default export extends static
get null undefined enum interface implements package private protected public readonly type declare
namespace module require abstract keyof never unknown number string boolean symbol bigint constructor
async then
func chan defer fallthrough goto map go select struct nil iota make append cap copy error byte rune
uint uint8 uint16 uint32 uint64 int8 int16 int32 int64 float32 float64 panic recover
done esac elif fi then local readonly shift echo printf exit source unset declare eval test
contract library pragma solidity mapping address payable memory storage calldata emit event modifier
require revert returns view pure external internal uint256 bytes32 bytes override virtual immutable
constant fallback receive msg sender value
""".split())


class Bad(Exception):
    pass


def git(cwd, *args, ok=(0,)):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True)
    if r.returncode not in ok:
        raise Bad(f"git {' '.join(args)} failed in {cwd}: {r.stderr.decode(errors='replace').strip()}")
    return r.returncode, r.stdout.decode(errors="replace")


def is_test(path):
    parts = path.split("/")
    name = parts[-1]
    return (any(p in ("test", "tests", "spec") for p in parts[:-1]) or name.startswith("test_")
            or any(m in name for m in ("_test.", ".test.", ".spec.")))


def changed_lines(diff):
    """(removed lines, with prose lines cut to their backticked spans; added lines from every file)."""
    removed, added = [], []
    in_hunk = prose = False
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            in_hunk = False
            prose = os.path.splitext(line.rsplit(" b/", 1)[-1])[1].lower() in PROSE
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("-"):
            removed.append(" ".join(CODE_SPAN.findall(line)) if prose else line[1:])
        elif in_hunk and line.startswith("+"):
            added.append(line[1:])
    return removed, added


def removed_names(cwd, head, diff):
    removed, added = changed_lines(diff)
    kept = set(IDENT.findall("\n".join(added)))
    names = []
    for line in removed:
        for n in IDENT.findall(line):
            if n not in kept and n.lower() not in STOP and n not in names:
                names.append(n)
    capped = len(names) > MAX_NAMES
    found, clean = [], []
    for n in names[:MAX_NAMES]:
        _, out = git(cwd, "grep", "-n", "-w", "-F", "-e", n, head, "--", ok=(0, 1))
        hits = [h[len(head) + 1:] if h.startswith(head + ":") else h for h in out.splitlines()]
        if hits:
            found.append({"name": n, "count": len(hits), "hits": [h[:200] for h in hits[:MAX_HITS]]})
        else:
            clean.append(n)
    return {"names": found, "removed_cleanly": clean, "total": len(names), "capped": capped}


def related_tests(cwd, head, changed):
    by_file = {}
    for _, _, path in changed:
        if is_test(path):
            continue
        stem = os.path.basename(path).split(".")[0]
        if not stem:
            continue
        _, out = git(cwd, "grep", "-l", "-w", "-F", "-e", stem, head, "--", ok=(0, 1))
        tests = [p[len(head) + 1:] if p.startswith(head + ":") else p for p in out.splitlines()]
        tests = [t for t in tests if is_test(t) and t != path]
        if tests:
            by_file[path] = tests
    return {"by_file": by_file, "changed_tests": [p for s, _, p in changed if is_test(p) and not s.startswith("D")]}


def build(cwd, base, head):
    for ref in (base, head):
        rc, _ = git(cwd, "rev-parse", "--verify", "--quiet", ref + "^{commit}", ok=(0, 1))
        if rc:
            raise Bad(f"cannot resolve {ref} in {cwd}")
    rng = f"{base}...{head}"
    _, status = git(cwd, *DIFF, "--name-status", rng, "--")
    rows = [line.split("\t") for line in status.split("\n") if line]
    changed = [(p[0], p[1] if len(p) == 3 else None, p[-1]) for p in rows if len(p) >= 2]
    _, diff = git(cwd, *DIFF, rng, "--")
    # Split on LF only so CR and Unicode line separators in the diff stay verbatim.
    lines = diff.split("\n")
    if lines[-1] == "":
        lines.pop()
    text = diff if len(lines) <= MAX_DIFF_LINES else "\n".join(lines[:MAX_DIFF_LINES]) + "\n"
    return {
        "changed_files": [{"status": s, "path": p, **({"old_path": o} if o else {})} for s, o, p in changed],
        "removed_names": removed_names(cwd, head, diff),
        "related_tests": related_tests(cwd, head, changed),
        "diff": {"text": text, "lines": len(lines),
                 "cut": max(0, len(lines) - MAX_DIFF_LINES),
                 "rest": f"git diff {rng} | tail -n +{MAX_DIFF_LINES + 1}"},
    }


def render(r):
    out = ["## Changed files", ""]
    out += ["\t".join([c["status"]] + ([c["old_path"]] if "old_path" in c else []) + [c["path"]])
            for c in r["changed_files"]] or ["(none)"]
    rn = r["removed_names"]
    out += ["", "## Removed or renamed names", "",
            "Heuristic: identifiers on removed lines that appear on no added line. "
            "A surviving reference is a lead to check, not a defect.", ""]
    for n in rn["names"]:
        out.append(f"{n['name']}: {n['count']} surviving reference{'s' if n['count'] != 1 else ''}")
        out += ["  " + h for h in n["hits"]]
        if n["count"] > len(n["hits"]):
            out.append(f"  ... {n['count'] - len(n['hits'])} more")
    if rn["removed_cleanly"]:
        out.append("removed cleanly: " + ", ".join(rn["removed_cleanly"]))
    if not rn["names"] and not rn["removed_cleanly"]:
        out.append("(none)")
    if rn["capped"]:
        out.append(f"cap hit: checked the first {MAX_NAMES} of {rn['total']} names")
    rt = r["related_tests"]
    out += ["", "## Related tests", "",
            "Heuristic: test files (by path) at head that mention a changed file's stem.", ""]
    for path, tests in rt["by_file"].items():
        out.append(f"{path}: " + ", ".join(tests))
    out.append("changed tests: " + (", ".join(rt["changed_tests"]) or "(none)"))
    d = r["diff"]
    out += ["", "## Diff", "", d["text"].removesuffix("\n")]
    if d["cut"]:
        out.append(f"... {d['cut']} of {d['lines']} diff lines cut; see the rest: {d['rest']}")
    return "\n".join(out) + "\n"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    opts = {"--cwd": ".", "--out": None}
    as_json = False
    pos = []
    while argv:
        a = argv.pop(0)
        if a in opts:
            if not argv:
                print(f"{a} needs a value", file=sys.stderr)
                return 2
            opts[a] = argv.pop(0)
        elif a == "--json":
            as_json = True
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            pos.append(a)
    if len(pos) != 2:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    try:
        report = build(os.path.abspath(opts["--cwd"]), pos[0], pos[1])
    except Bad as e:
        print(f"review-pre-read.py: {e}", file=sys.stderr)
        return 2
    text = json.dumps(report, indent=2) + "\n" if as_json else render(report)
    if opts["--out"]:
        with open(opts["--out"], "w") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
