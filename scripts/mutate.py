#!/usr/bin/env python3
"""Prove a test catches a bug: apply each mutant to the source, run a test command, and expect it to fail.

Usage: mutate.py [--json] [--out DIR] [--keep] [--allow-dirty] [--no-baseline] SPEC

SPEC is a JSON file, or - for stdin:

  {
    "cwd": "path/to/repo",            optional, relative to the current directory
    "test": ["go", "test", "./calc"],  default command: an argv list or a shell string
    "mode": "auto",                    optional: auto, overlay, or in-place
    "mutants": [
      {"name": "off-by-one", "file": "calc/sum.go", "old": "i < n", "new": "i <= n"},
      {"name": "fix-reverted", "file": "calc/sum.go", "rev": "HEAD~1"},
      {"name": "old-test", "files": [{"file": "calc/sum.go", "old": "+ 1", "new": "+ 2"},
                                     {"file": "calc/sum_test.go", "rev": "HEAD~1"}]}
    ]
  }

A mutant changes one file ("file") or several ("files"). Each change is a text swap ("old" must occur
exactly once and differ from "new") or a whole file taken from git ("rev": the content of
`git show <rev>:<file>`). File paths are relative to "cwd". A mutant may set its own "test" and "mode".

Modes:
  overlay   The mutated files go to the scratch dir and the command runs with GOFLAGS=-overlay=<json>,
            so the worktree is never written. auto picks it when the command runs go test, go vet, or
            go build and every mutated file is a .go file.
  in-place  The mutated files are written over the originals, the command runs, and the original bytes
            are restored, also on SIGINT and SIGTERM. Backups stay in the scratch dir. A file with
            uncommitted changes is refused unless --allow-dirty is passed.

Before any mutant runs, each distinct command runs once unmutated and must pass; otherwise a failure under
a mutant proves nothing and its mutants are invalid. --no-baseline skips this.

Verdicts, one line per mutant on stdout (--json prints a list of objects instead):
  killed       the command exited nonzero
  survived     the command exited zero
  build-error  a Go command failed to compile or set up a package, or failed without a test failure
  invalid      the mutant cannot be applied (missing file, old not found or not unique, unknown rev,
               no-op change, dirty file), the command was not found, or the baseline failed

Exit codes: 0 every mutant killed, 1 a mutant survived or hit build-error, 2 bad input or an invalid
mutant, 3 a file could not be restored (its backup path is printed), 128+N interrupted by signal N.

The scratch dir is a new temp dir, or --out DIR. It holds one directory per mutant with the command
output (output.log), backups, and overlay files. A temp dir is removed when every mutant is killed,
unless --keep is passed; otherwise its path is printed on stderr.

Go example, run from a module root; the worktree is never written:

  printf '%s' '{"test": ["go", "test", "./calc"], "mutants": [
    {"name": "fix-reverted", "file": "calc/sum.go", "rev": "HEAD~1"}]}' | mutate.py -

Non-Go example, the file is edited in place and restored:

  printf '%s' '{"test": "python3 -m pytest -q tests/test_parse.py", "mutants": [
    {"name": "drop-strip", "file": "parse.py", "old": "line.strip()", "new": "line"}]}' | mutate.py -
"""

import argparse
import contextlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

GO_SUBCOMMANDS = {"test", "vet", "build"}
MODES = {"auto", "overlay", "in-place"}
BUILD_FAILED = re.compile(r"\[(?:build|setup) failed\]")
TEST_FAILED = re.compile(r"--- FAIL|^FAIL\s+\S+\s+\d+(?:\.\d+)?s\s*$|^panic: ", re.M)
GO_TOOL_ERROR = re.compile(r"^(?:go|vet): ", re.M)
CAUGHT = (signal.SIGINT, signal.SIGTERM)


class SpecError(Exception):
    pass


class Invalid(Exception):
    pass


class Interrupted(BaseException):
    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


class RestoreFailed(Exception):
    pass


_interrupted = None


def on_signal(signum, frame):
    global _interrupted
    # Only the first signal interrupts; later ones must not abort the cleanup it starts.
    if _interrupted is None:
        _interrupted = signum
        raise Interrupted(signum)


@contextlib.contextmanager
def signals_blocked():
    old = signal.pthread_sigmask(signal.SIG_BLOCK, CAUGHT)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


def check_command(cmd, where):
    if isinstance(cmd, str) and cmd.strip():
        return cmd
    if isinstance(cmd, list) and cmd and all(isinstance(a, str) for a in cmd):
        return cmd
    raise SpecError("%s: test must be a non-empty argv list or shell string" % where)


def check_mode(mode, where):
    if mode not in MODES:
        raise SpecError("%s: mode must be one of %s" % (where, ", ".join(sorted(MODES))))
    return mode


def parse_change(raw, where):
    if not isinstance(raw, dict):
        raise SpecError("%s: a change must be an object" % where)
    path = raw.get("file")
    if not isinstance(path, str) or not path:
        raise SpecError("%s: file must be a non-empty string" % where)
    has_rev = "rev" in raw
    has_swap = "old" in raw or "new" in raw
    if has_rev == has_swap:
        raise SpecError("%s: give either rev or old and new" % where)
    if has_rev:
        if not isinstance(raw["rev"], str) or not raw["rev"]:
            raise SpecError("%s: rev must be a non-empty string" % where)
        return {"file": path, "rev": raw["rev"]}
    if not isinstance(raw.get("old"), str) or not isinstance(raw.get("new"), str):
        raise SpecError("%s: old and new must both be strings" % where)
    return {"file": path, "old": raw["old"], "new": raw["new"]}


def load_spec(text):
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as e:
        raise SpecError("spec is not valid JSON: %s" % e)
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    cwd = spec.get("cwd", ".")
    if not isinstance(cwd, str) or not os.path.isdir(cwd):
        raise SpecError("cwd is not a directory: %r" % (cwd,))
    default_test = check_command(spec["test"], "spec") if "test" in spec else None
    default_mode = check_mode(spec.get("mode", "auto"), "spec")
    raw_mutants = spec.get("mutants")
    if not isinstance(raw_mutants, list) or not raw_mutants:
        raise SpecError("mutants must be a non-empty list")
    mutants, names = [], set()
    for i, raw in enumerate(raw_mutants):
        where = "mutants[%d]" % i
        if not isinstance(raw, dict):
            raise SpecError("%s: must be an object" % where)
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise SpecError("%s: name must be a non-empty string" % where)
        if name in names:
            raise SpecError("%s: duplicate name %r" % (where, name))
        names.add(name)
        where = "mutant %r" % name
        if ("file" in raw) == ("files" in raw):
            raise SpecError("%s: give either file or files" % where)
        if "files" in raw:
            if not isinstance(raw["files"], list) or not raw["files"]:
                raise SpecError("%s: files must be a non-empty list" % where)
            changes = [parse_change(c, where) for c in raw["files"]]
        else:
            changes = [parse_change(raw, where)]
        paths = [os.path.normpath(os.path.join(cwd, c["file"])) for c in changes]
        if len(set(paths)) != len(paths):
            raise SpecError("%s: a file appears twice; one change per file" % where)
        if "test" in raw:
            test = check_command(raw["test"], where)
        elif default_test is not None:
            test = default_test
        else:
            raise SpecError("%s: no test command (set test on the spec or the mutant)" % where)
        mode = check_mode(raw.get("mode", default_mode), where)
        mutants.append({"name": name, "changes": changes, "test": test, "mode": mode})
    return os.path.abspath(cwd), mutants


def go_subcommands(cmd):
    if isinstance(cmd, str):
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            return set()
    else:
        tokens = cmd
    return {b for a, b in zip(tokens, tokens[1:]) if os.path.basename(a) == "go" and b in GO_SUBCOMMANDS}


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True)


def show_rev(path, rev):
    top = git(os.path.dirname(path), "rev-parse", "--show-toplevel")
    if top.returncode:
        raise Invalid("%s is not in a git work tree" % path)
    root = os.path.realpath(top.stdout.decode().strip())
    rel = os.path.relpath(os.path.realpath(path), root)
    p = git(root, "show", "%s:%s" % (rev, rel))
    if p.returncode:
        raise Invalid("git show %s:%s: %s" % (rev, rel, p.stderr.decode().strip()))
    return p.stdout


def apply_change(change, path):
    if not os.path.isfile(path):
        raise Invalid("%s: no such file" % change["file"])
    with open(path, "rb") as f:
        original = f.read()
    if "rev" in change:
        mutated = show_rev(path, change["rev"])
        if mutated == original:
            raise Invalid("%s at %s is identical to the worktree file" % (change["file"], change["rev"]))
        return original, mutated
    old, new = change["old"], change["new"]
    if not old:
        raise Invalid("%s: old is empty" % change["file"])
    if old == new:
        raise Invalid("%s: old and new are the same" % change["file"])
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError:
        raise Invalid("%s: not UTF-8 text" % change["file"])
    at = text.find(old)
    if at < 0:
        raise Invalid("%s: old not found" % change["file"])
    if text.find(old, at + 1) >= 0:
        raise Invalid("%s: old occurs more than once" % change["file"])
    return original, (text[:at] + new + text[at + len(old):]).encode("utf-8")


def dirty_reason(path):
    p = git(os.path.dirname(path), "status", "--porcelain", "--ignored", "--", os.path.basename(path))
    if p.returncode:
        return "is not in a git work tree"
    if p.stdout.strip():
        return "has uncommitted changes"
    return None


def stop(proc):
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, None)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        try:
            proc.wait(wait)
            return
        except subprocess.TimeoutExpired:
            pass
    proc.wait()


def run(cmd, cwd, env, log_path):
    """Run cmd with output to log_path; return (exit code, output). Raises Invalid when cmd cannot start."""
    shell = isinstance(cmd, str)
    # The go command resolves files from $PWD when it names the working directory, and overlay keys must
    # match that spelling; an inherited $PWD would point at the caller's directory instead.
    env = dict(os.environ if env is None else env, PWD=cwd)
    with open(log_path, "wb") as log:
        try:
            # A new session lets stop() kill the whole tree (go test spawns test binaries).
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, shell=shell, stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            raise Invalid("cannot run %s: %s" % (cmd[0], e.strerror))
        try:
            code = proc.wait()
        except BaseException:
            stop(proc)
            raise
    with open(log_path, "rb") as f:
        output = f.read().decode("utf-8", "replace")
    if shell and code in (126, 127):
        raise Invalid("shell exit %d (command not found or not executable); see %s" % (code, log_path))
    return code, output


def classify(code, output, go_kinds):
    if code == 0:
        return "survived", None
    if not go_kinds:
        return "killed", None
    if BUILD_FAILED.search(output):
        return "build-error", "a package failed to build"
    if TEST_FAILED.search(output):
        return "killed", None
    if "vet" in go_kinds and not GO_TOOL_ERROR.search(output):
        return "killed", None
    return "build-error", "the go command failed without a test failure"


def restore(applied):
    failed = []
    for path, original, backup in applied:
        try:
            with open(path, "wb") as f:
                f.write(original)
            with open(path, "rb") as f:
                if f.read() == original:
                    continue
        except OSError:
            pass
        failed.append("%s (backup: %s)" % (path, backup))
    return failed


def run_in_place(edits, cmd, cwd, workdir, log_path):
    backups = os.path.join(workdir, "backup")
    os.makedirs(backups, exist_ok=True)
    applied = []
    try:
        with signals_blocked():
            for i, (path, original, mutated) in enumerate(edits):
                backup = os.path.join(backups, "%d-%s" % (i, os.path.basename(path)))
                with open(backup, "wb") as f:
                    f.write(original)
                applied.append((path, original, backup))
                with open(path, "wb") as f:
                    f.write(mutated)
        return run(cmd, cwd, None, log_path)
    finally:
        failed = []
        try:
            with signals_blocked():
                failed = restore(applied)
        finally:
            # A signal held during restore is delivered on unblock; a restore failure must still surface.
            if failed:
                raise RestoreFailed("could not restore: " + "; ".join(failed))


def run_overlay(edits, cmd, cwd, workdir, log_path):
    files = os.path.join(workdir, "overlay")
    os.makedirs(files, exist_ok=True)
    replace = {}
    for i, (path, _, mutated) in enumerate(edits):
        copy = os.path.join(files, "%d-%s" % (i, os.path.basename(path)))
        with open(copy, "wb") as f:
            f.write(mutated)
        # The go command may see the module through a symlinked or a resolved path, so map both.
        for key in {os.path.abspath(path), os.path.realpath(path)}:
            replace[key] = copy
    overlay = os.path.join(workdir, "overlay.json")
    if re.search(r"\s", overlay):
        raise Invalid("scratch path %r contains whitespace, which GOFLAGS cannot carry; pass --out" % workdir)
    with open(overlay, "w") as f:
        json.dump({"Replace": replace}, f, indent=1)
    env = dict(os.environ)
    env["GOFLAGS"] = (env.get("GOFLAGS", "") + " -overlay=" + overlay).strip()
    return run(cmd, cwd, env, log_path)


def slug(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")[:60] or "mutant"


def run_mutant(index, m, cwd, scratch, args, baselines):
    result = {"name": m["name"], "verdict": "invalid", "mode": None, "files": [c["file"] for c in m["changes"]],
              "test": m["test"], "exit": None, "seconds": None, "log": None, "reason": None}
    go_kinds = go_subcommands(m["test"])
    workdir = os.path.join(scratch, "%02d-%s" % (index, slug(m["name"])))
    try:
        edits = []
        for c in m["changes"]:
            path = os.path.normpath(os.path.join(cwd, c["file"]))
            original, mutated = apply_change(c, path)
            edits.append((path, original, mutated))
        mode = m["mode"]
        if mode == "auto":
            all_go = all(p.endswith(".go") for p, _, _ in edits)
            mode = "overlay" if go_kinds and all_go else "in-place"
        result["mode"] = mode
        if mode == "in-place" and not args.allow_dirty:
            for (path, _, _), c in zip(edits, m["changes"]):
                why = dirty_reason(path)
                if why:
                    raise Invalid("%s %s; in-place mode needs a committed file (or --allow-dirty)" % (c["file"], why))
        base = baselines.get(json.dumps(m["test"]))
        if base:
            raise Invalid(base)
        os.makedirs(workdir, exist_ok=True)
        log_path = os.path.join(workdir, "output.log")
        result["log"] = log_path
        start = time.monotonic()
        runner = run_overlay if mode == "overlay" else run_in_place
        code, output = runner(edits, m["test"], cwd, workdir, log_path)
        result["seconds"] = round(time.monotonic() - start, 2)
        result["exit"] = code
        result["verdict"], result["reason"] = classify(code, output, go_kinds)
    except Invalid as e:
        result["verdict"], result["reason"] = "invalid", str(e)
    return result


def run_baselines(mutants, cwd, scratch):
    """Run each distinct command once unmutated; map command key to a failure reason, or None."""
    out = {}
    for m in mutants:
        key = json.dumps(m["test"])
        if key in out:
            continue
        log_path = os.path.join(scratch, "baseline-%d.log" % len(out))
        try:
            code, output = run(m["test"], cwd, None, log_path)
        except Invalid as e:
            out[key] = "baseline: %s" % e
            continue
        out[key] = None if code == 0 else "baseline: the command exits %d without any mutant; see %s" % (code, log_path)
    return out


def describe(r, kept):
    if r["verdict"] == "invalid":
        detail = r["reason"]
    else:
        detail = "exit %s, %.1fs, %s" % (r["exit"], r["seconds"], r["mode"])
        if r["reason"]:
            detail += ", " + r["reason"]
        if kept:
            detail += ", log " + r["log"]
    return "%-11s %s  %s" % (r["verdict"], r["name"], detail)


def exit_code(results):
    verdicts = {r["verdict"] for r in results}
    if "invalid" in verdicts:
        return 2
    if verdicts - {"killed"}:
        return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mutate.py", description=__doc__.split("\n", 1)[0],
                                 epilog=__doc__.split("\n", 1)[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", metavar="SPEC", help="JSON spec file, or - for stdin")
    ap.add_argument("--json", action="store_true", help="print the results as a JSON list")
    ap.add_argument("--out", metavar="DIR", help="scratch dir for logs, backups, and overlays (kept)")
    ap.add_argument("--keep", action="store_true", help="keep the temp scratch dir even when every mutant is killed")
    ap.add_argument("--allow-dirty", action="store_true", help="allow in-place mode on files with uncommitted changes")
    ap.add_argument("--no-baseline", action="store_true", help="skip the unmutated run of each command")
    args = ap.parse_args(argv)

    try:
        if args.spec == "-":
            text = sys.stdin.read()
        else:
            with open(args.spec) as f:
                text = f.read()
        cwd, mutants = load_spec(text)
    except (OSError, SpecError) as e:
        print("mutate: %s" % e, file=sys.stderr)
        return 2

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        scratch = os.path.abspath(args.out)
    else:
        scratch = tempfile.mkdtemp(prefix="mutate-")

    for s in CAUGHT:
        signal.signal(s, on_signal)
    results, code = [], None
    try:
        baselines = {} if args.no_baseline else run_baselines(mutants, cwd, scratch)
        for i, m in enumerate(mutants):
            results.append(run_mutant(i, m, cwd, scratch, args, baselines))
    except Interrupted as e:
        print("mutate: interrupted by signal %d; every in-place file was restored" % e.signum, file=sys.stderr)
        code = 128 + e.signum
    except RestoreFailed as e:
        print("mutate: %s" % e, file=sys.stderr)
        code = 3
    finally:
        for s in CAUGHT:
            signal.signal(s, signal.SIG_DFL)

    if code is None:
        code = exit_code(results)
    kept = bool(args.out) or args.keep or code != 0
    if not kept:
        shutil.rmtree(scratch, ignore_errors=True)
        for r in results:
            r["log"] = None
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print(describe(r, kept))
    if kept and not args.out:
        print("mutate: scratch dir %s" % scratch, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
