#!/usr/bin/env bash
# Reclaim bulk from idle task dirs under the task root. Never deletes notes.
# usage: task-prune.sh [--older-than <N>d] [--apply] [--json]
#
# Root: $HWORKS_TASKS_DIR, default ${XDG_STATE_HOME:-~/.local/state}/agent-tasks.
# A unit is <root>/<repo>/<branch>/<slug>, <root>/_misc/<slug>, or any other top-level
# dir. A unit is idle when its newest file is older than --older-than (default 14d).
# In idle units, candidates are dependency, VCS, and cache dirs (.git, node_modules,
# .terraform, .venv, venv, __pycache__, .cache, *cache) and files over 1 MiB other than
# *.md, *.jsonl, and .task. Symlinks are never followed. Default is a dry run;
# --apply deletes the candidates and then the dirs they leave empty.
set -euo pipefail

older=14d; apply=0; json=0
while [ $# -gt 0 ]; do
  case "$1" in
    --older-than) older=${2:?--older-than needs a value}; shift 2 ;;
    --apply) apply=1; shift ;;
    --json) json=1; shift ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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


def units():
    for top in real_dirs(""):
        if "--" in top or top.startswith("local--"):
            for branch in real_dirs(top):
                yield from real_dirs(branch)
        elif top == "_misc":
            yield from real_dirs(top)
        else:
            yield top


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


def is_bulk(name):
    low = name.lower()
    return low in BULK_DIRS or low.endswith("cache")


def candidates(unit, unit_fd):
    found = []
    for d, dirs, fs, dfd in os.fwalk(".", dir_fd=unit_fd):
        here = os.path.normpath(os.path.join(unit, d))
        keep = []
        for n in sorted(dirs):
            try:
                if not stat.S_ISDIR(lstat_at(n, dfd).st_mode):
                    continue
            except OSError:
                continue
            if is_bulk(n):
                found.append((os.path.join(here, n), sum(st.st_size for st in files(n, dfd)), "dir"))
            else:
                keep.append(n)
        dirs[:] = keep
        for f in sorted(fs):
            if f.endswith(KEEP_SUFFIXES) or f == ".task":
                continue
            try:
                st = lstat_at(f, dfd)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode) and st.st_size > BIG:
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
for unit in units():
    try:
        unit_fd = open_rel(unit)
    except OSError as err:
        print(f"task-prune: cannot open {unit}: {err}; skipping it", file=sys.stderr)
        continue
    try:
        if newest(unit, unit_fd) >= cutoff:
            report["active_units"] += 1
            continue
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
    print(f"units: {report['idle_units']} idle, {report['active_units']} active (older than {report['older_than']})")
PY
