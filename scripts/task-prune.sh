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
import json, os, re, shutil, stat, sys, time

BULK_DIRS = {".git", "node_modules", ".terraform", ".venv", "venv", "__pycache__", ".cache"}
KEEP_SUFFIXES = (".md", ".jsonl")
BIG = 1 << 20


def die(msg):
    print(f"task-prune: {msg}", file=sys.stderr)
    sys.exit(2)


raw = os.environ.get("PRUNE_ROOT", "")
if not raw:
    die("task root is empty; refusing")
if not os.path.isdir(raw) or os.path.islink(raw):
    die(f"task root {raw} does not exist or is not a directory; refusing")
root = os.path.realpath(raw)
home = os.path.realpath(os.path.expanduser("~")) if os.environ.get("HOME") else None
if root == os.path.sep or root == home:
    die(f"task root {root} is / or $HOME; refusing")

m = re.fullmatch(r"(\d+)d", os.environ["PRUNE_OLDER"])
if not m:
    die("--older-than must look like <N>d")
cutoff = time.time() - int(m.group(1)) * 86400
apply = os.environ["PRUNE_APPLY"] == "1"
as_json = os.environ["PRUNE_JSON"] == "1"


def real_dirs(path):
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name)
    except OSError:
        return []
    return [e.path for e in entries if e.is_dir(follow_symlinks=False)]


def units():
    for top in real_dirs(root):
        name = os.path.basename(top)
        if "--" in name or name.startswith("local--"):
            for branch in real_dirs(top):
                yield from real_dirs(branch)
        elif name == "_misc":
            yield from real_dirs(top)
        else:
            yield top


def files(path):
    for d, dirs, fs in os.walk(path, followlinks=False):
        for f in fs:
            p = os.path.join(d, f)
            st = os.lstat(p)
            if stat.S_ISREG(st.st_mode):
                yield p, st


def newest(unit):
    times = [st.st_mtime for _, st in files(unit)]
    return max(times) if times else os.lstat(unit).st_mtime


def is_bulk(name):
    low = name.lower()
    return low in BULK_DIRS or low.endswith("cache")


def candidates(unit):
    found = []
    for d, dirs, fs in os.walk(unit, followlinks=False):
        keep = []
        for n in sorted(dirs):
            p = os.path.join(d, n)
            if os.path.islink(p):
                continue
            if is_bulk(n):
                found.append((p, sum(st.st_size for _, st in files(p)), "dir"))
            else:
                keep.append(n)
        dirs[:] = keep
        for f in sorted(fs):
            if f.endswith(KEEP_SUFFIXES) or f == ".task":
                continue
            p = os.path.join(d, f)
            st = os.lstat(p)
            if stat.S_ISREG(st.st_mode) and st.st_size > BIG:
                found.append((p, st.st_size, "file"))
    return found


def inside(path):
    parent = os.path.realpath(os.path.dirname(path))
    return parent == root or parent.startswith(root + os.sep)


def delete(path, kind, unit):
    if os.path.islink(path) or not inside(path):
        return False
    if kind == "dir":
        shutil.rmtree(path)
    else:
        os.unlink(path)
    d = os.path.dirname(path)
    while d != unit and d.startswith(unit + os.sep):
        try:
            os.rmdir(d)
        except OSError:
            break
        d = os.path.dirname(d)
    return True


report = {"root": root, "older_than": os.environ["PRUNE_OLDER"], "apply": apply,
          "candidates": [], "reclaimable_bytes": 0, "idle_units": 0, "active_units": 0}
if apply:
    report["freed_bytes"] = 0
for unit in units():
    if newest(unit) >= cutoff:
        report["active_units"] += 1
        continue
    report["idle_units"] += 1
    for path, size, kind in candidates(unit):
        report["candidates"].append({"path": os.path.relpath(path, root), "bytes": size, "kind": kind})
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
