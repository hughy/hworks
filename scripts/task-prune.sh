#!/usr/bin/env bash
# Reclaim bulk from idle task dirs under the task root. Never deletes notes.
# usage: task-prune.sh [--older-than <N>d] [--apply] [--json]
#
# Root: $HWORKS_TASKS_DIR, default ${XDG_STATE_HOME:-~/.local/state}/agent-tasks.
# A unit is <root>/<repo>/<branch>/<slug> (repo is local--<name> or has two or more
# "--"), <root>/_misc/<slug>, or any other top-level dir. Files directly in a repo,
# branch, or _misc dir form one more unit per dir. A unit is idle when its newest file
# is older than --older-than (default 14d).
# In idle units, candidates are dependency, VCS, and cache dirs (.git, node_modules,
# .terraform, .venv, venv, __pycache__, .cache, *cache) and files over 1 MiB other than
# *.md, *.jsonl, and .task. A bulk dir goes whole, including any .md files in it (those
# are dependency content), unless it holds a .task file or lies under orchestrate/.
# Symlinks are never followed. Default is a dry run; --apply deletes the candidates
# and then the dirs they leave empty.
set -euo pipefail

older=14d; apply=0; json=0
while [ $# -gt 0 ]; do
  case "$1" in
    --older-than) older=${2:?--older-than needs a value}; shift 2 ;;
    --apply) apply=1; shift ;;
    --json) json=1; shift ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

export PRUNE_ROOT=${HWORKS_TASKS_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/agent-tasks}
export PRUNE_OLDER=$older PRUNE_APPLY=$apply PRUNE_JSON=$json

exec python3 - <<'PY'
import json, os, re, stat, sys, time

BULK_DIRS = {".git", "node_modules", ".terraform", ".venv", "venv", "__pycache__", ".cache"}
KEEP_SUFFIXES = (".md", ".jsonl")
BIG = 1 << 20
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def die(msg):
    print(f"task-prune: {msg}", file=sys.stderr)
    sys.exit(2)


raw = os.environ.get("PRUNE_ROOT", "")
if not raw:
    die("task root is empty; refusing")
if not os.path.isdir(raw) or os.path.islink(raw):
    die(f"task root {raw} does not exist or is not a directory; refusing")
# Every scan and delete goes through this one fd, so swapping an ancestor of the root
# for a symlink after this point cannot move the work outside the checked root.
try:
    root_fd = os.open(raw, DIR_FLAGS)
except OSError as err:
    die(f"cannot open task root {raw}: {err}; refusing")
root = os.path.realpath(raw)
root_st = os.fstat(root_fd)
if not os.path.samestat(root_st, os.stat(root)):
    die(f"task root {raw} changed while opening; refusing")
unsafe = [os.path.sep] + ([os.path.expanduser("~")] if os.environ.get("HOME") else [])
for bad in unsafe:
    if os.path.exists(bad) and os.path.samestat(root_st, os.stat(bad)):
        die(f"task root {root} is / or $HOME; refusing")

m = re.fullmatch(r"(\d+)d", os.environ["PRUNE_OLDER"])
if not m:
    die("--older-than must look like <N>d")
cutoff = time.time() - int(m.group(1)) * 86400
apply = os.environ["PRUNE_APPLY"] == "1"
as_json = os.environ["PRUNE_JSON"] == "1"


def open_rel(rel):
    # Open a root-relative dir one component at a time with O_NOFOLLOW.
    fd = os.dup(root_fd)
    try:
        for name in rel.split(os.sep) if rel else []:
            nxt = os.open(name, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nxt
    except OSError:
        os.close(fd)
        raise
    return fd


def real_dirs(rel):
    try:
        fd = open_rel(rel)
    except OSError:
        return []
    try:
        with os.scandir(fd) as it:
            names = sorted(e.name for e in it if e.is_dir(follow_symlinks=False))
    except OSError:
        names = []
    finally:
        os.close(fd)
    return [os.path.join(rel, n) if rel else n for n in names]


def is_repo(name):
    return name.startswith("local--") or name.count("--") >= 2


def units():
    # Yields (path, shallow). A shallow unit is only the regular files directly in path.
    for top in real_dirs(""):
        if is_repo(top):
            yield top, True
            for branch in real_dirs(top):
                yield branch, True
                for slug in real_dirs(branch):
                    yield slug, False
        elif top == "_misc":
            yield top, True
            for slug in real_dirs(top):
                yield slug, False
        else:
            yield top, False


def raise_error(err):
    raise err


def lstat_at(name, dir_fd):
    return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)


def files(top, dir_fd, strict=False):
    # os.fwalk does not descend into symlinks when follow_symlinks is False.
    for _, _, fs, dfd in os.fwalk(top, onerror=raise_error if strict else None, dir_fd=dir_fd):
        for f in fs:
            try:
                st = lstat_at(f, dfd)
            except OSError:
                if strict:
                    raise
                continue
            if stat.S_ISREG(st.st_mode):
                yield st


def newest(unit, unit_fd):
    # A scan that cannot read every dir may miss fresh files, so treat the unit as active.
    try:
        times = [st.st_mtime for st in files(".", unit_fd, strict=True)]
        return max(times) if times else os.fstat(unit_fd).st_mtime
    except OSError as err:
        print(f"task-prune: cannot scan {unit}: {err}; treating it as active", file=sys.stderr)
        return float("inf")


def direct_files(dir_fd):
    out = []
    with os.scandir(dir_fd) as it:
        names = sorted(e.name for e in it)
    for n in names:
        try:
            st = lstat_at(n, dir_fd)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            out.append((n, st))
    return out


def prunable(name, st):
    return not name.endswith(KEEP_SUFFIXES) and name != ".task" and st.st_size > BIG


def bulk_scan(top, dir_fd):
    # Returns (bytes, holds_task). A dir that cannot be read fully counts as holding a
    # .task file, so it is never deleted whole.
    size = 0
    try:
        for _, _, fs, dfd in os.fwalk(top, onerror=raise_error, dir_fd=dir_fd):
            for f in fs:
                st = lstat_at(f, dfd)
                if stat.S_ISREG(st.st_mode):
                    size += st.st_size
                    if f == ".task":
                        return size, True
    except OSError:
        return size, True
    return size, False


def is_bulk(name):
    low = name.lower()
    return low in BULK_DIRS or low.endswith("cache")


def candidates(unit, unit_fd):
    found = []
    for d, dirs, fs, dfd in os.fwalk(".", dir_fd=unit_fd):
        here = os.path.normpath(os.path.join(unit, d))
        in_store = "orchestrate" in os.path.normpath(d).split(os.sep)
        keep = []
        for n in sorted(dirs):
            try:
                if not stat.S_ISDIR(lstat_at(n, dfd).st_mode):
                    continue
            except OSError:
                continue
            if is_bulk(n) and not in_store:
                size, holds_task = bulk_scan(n, dfd)
                if not holds_task:
                    found.append((os.path.join(here, n), size, "dir"))
                    continue
            keep.append(n)
        dirs[:] = keep
        for f in sorted(fs):
            try:
                st = lstat_at(f, dfd)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode) and prunable(f, st):
                found.append((os.path.join(here, f), st.st_size, "file"))
    return found


def rmtree_at(name, parent_fd):
    fd = os.open(name, DIR_FLAGS, dir_fd=parent_fd)
    try:
        with os.scandir(fd) as it:
            entries = [(e.name, e.is_dir(follow_symlinks=False)) for e in it]
        for n, is_dir in entries:
            if is_dir:
                rmtree_at(n, fd)
            else:
                os.unlink(n, dir_fd=fd)
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=parent_fd)


def delete(path, kind, unit):
    # path and unit are root-relative. Every step goes through dir fds opened with
    # O_NOFOLLOW from root_fd, so a dir swapped for a symlink cannot redirect deletion.
    rel = path.split(os.sep)
    depth = len(unit.split(os.sep))
    fds = [os.dup(root_fd)]
    try:
        for name in rel[:-1]:
            fds.append(os.open(name, DIR_FLAGS, dir_fd=fds[-1]))
        st = lstat_at(rel[-1], fds[-1])
        if kind == "dir" and stat.S_ISDIR(st.st_mode):
            rmtree_at(rel[-1], fds[-1])
        elif kind == "file" and stat.S_ISREG(st.st_mode):
            os.unlink(rel[-1], dir_fd=fds[-1])
        else:
            return False
        for i in range(len(rel) - 1, depth, -1):
            try:
                os.rmdir(rel[i - 1], dir_fd=fds[i - 1])
            except OSError:
                break
        return True
    except OSError:
        return False
    finally:
        for fd in fds:
            os.close(fd)


report = {"root": root, "older_than": os.environ["PRUNE_OLDER"], "apply": apply,
          "candidates": [], "reclaimable_bytes": 0, "idle_units": 0, "active_units": 0}
if apply:
    report["freed_bytes"] = 0
for unit, shallow in units():
    try:
        unit_fd = open_rel(unit)
    except OSError as err:
        print(f"task-prune: cannot open {unit}: {err}; skipping it", file=sys.stderr)
        continue
    try:
        if shallow:
            try:
                direct = direct_files(unit_fd)
            except OSError as err:
                print(f"task-prune: cannot scan {unit}: {err}; skipping it", file=sys.stderr)
                continue
            if not direct:
                continue
            if max(st.st_mtime for _, st in direct) >= cutoff:
                report["active_units"] += 1
                continue
            report["idle_units"] += 1
            found = [(os.path.join(unit, n), st.st_size, "file")
                     for n, st in direct if prunable(n, st)]
        elif newest(unit, unit_fd) >= cutoff:
            report["active_units"] += 1
            continue
        else:
            report["idle_units"] += 1
            found = candidates(unit, unit_fd)
    finally:
        os.close(unit_fd)
    for path, size, kind in found:
        report["candidates"].append({"path": path, "bytes": size, "kind": kind})
        report["reclaimable_bytes"] += size
        if apply and delete(path, kind, unit):
            report["freed_bytes"] += size

def human(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


if as_json:
    json.dump(report, sys.stdout, indent=2)
    print()
else:
    for c in report["candidates"]:
        print(f"{human(c['bytes']):>10}  {c['kind']:<4}  {c['path']}")
    print(f"reclaimable: {report['reclaimable_bytes']} bytes ({human(report['reclaimable_bytes'])})")
    if apply:
        print(f"freed: {report['freed_bytes']} bytes ({human(report['freed_bytes'])})")
    else:
        print("dry run: nothing deleted; rerun with --apply to delete")
    print(f"units: {report['idle_units']} idle (no file newer than {report['older_than']}), "
          f"{report['active_units']} active")
PY
