#!/usr/bin/env bash
# Print (and create) the scratch directory for a task: $TASK_DIR.
# usage: task-dir.sh <task-slug> [path]
#
# Inside a git repo:  <root>/<host>--<owner>--<repo>/<branch>/<task-slug>
# Outside one:        <root>/_misc/<task-slug>
# <root> is $HWORKS_TASKS_DIR, default ~/.local/state/agent-tasks. [path] defaults to the
# current directory. Worktrees of one repo share the repo level and differ by branch.
set -euo pipefail

clean() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -e 's#/#--#g' -e 's/[^a-z0-9._-]/-/g' -e 's/^[.-]*//'; }

slug=$(clean "${1:-}")
[ -n "$slug" ] || { echo "usage: task-dir.sh <task-slug> [path]" >&2; exit 2; }
dir=${2:-.}
root=${HWORKS_TASKS_DIR:-$HOME/.local/state/agent-tasks}

if top=$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null); then
  url=$(git -C "$dir" remote get-url origin 2>/dev/null || true)
  # https://host/owner/repo(.git), ssh://git@host[:port]/owner/repo, git@host:owner/repo
  hostpath=$(printf '%s' "$url" | sed -E -e 's#^[a-z+]+://##' -e 's#^[^@/]+@##' -e 's#^([^:/]+):([0-9]+/)?#\1/#' -e 's#\.git/?$##' -e 's#/+$##')
  if [ -n "$hostpath" ] && [ "${hostpath#*/}" != "$hostpath" ]; then
    repo=$(clean "$(printf '%s' "$hostpath" | sed 's#/#--#g')")
  else
    repo=local--$(clean "$(basename "$top")")
  fi
  branch=$(git -C "$dir" branch --show-current 2>/dev/null || true)
  [ -n "$branch" ] || branch=detached-$(git -C "$dir" rev-parse --short HEAD 2>/dev/null || echo unborn)
  out="$root/$repo/$(clean "$branch")/$slug"
else
  out="$root/_misc/$slug"
fi

mkdir -p "$out"
printf '%s\n' "$out"
