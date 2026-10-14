#!/usr/bin/env bash
# Print (and create) the scratch directory for a task: $TASK_DIR.
# usage: task-dir.sh <task-slug> [path]
#
# Inside a git repo:  <root>/<host>--<owner>--<repo>/<branch>/<task-slug>
# Outside one:        <root>/_misc/<task-slug>
# <root> is $HWORKS_TASKS_DIR, default $XDG_STATE_HOME/agent-tasks ($XDG_STATE_HOME defaults
# to ~/.local/state). [path] defaults to the current directory. Worktrees of one repo share the
# repo level and differ by branch.
#
# <branch> is the branch lowercased with / as --. When that can lose information (an uppercase
# letter or other character outside [a-z0-9._/-], a -- substring, a leading . or -, or a -/ or
# /- substring), it gets + plus the first 8 hex chars of the SHA-1 (sha1sum or shasum) of the raw
# branch name. clean() never emits +, so two different branches never share a dir (up to hash
# collisions).
# A newly created task dir gets a .task file of key=value lines: created, repo, branch, slug, cwd.
set -euo pipefail

clean() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -e 's#/#--#g' -e 's/[^a-z0-9._-]/-/g' -e 's/^[.-]*//'; }

lossless() {
  case "$1" in
    *[!a-z0-9._/-]* | *--* | [.-]* | *-/* | */-*) return 1 ;;
  esac
}

sha1() { if command -v sha1sum >/dev/null; then sha1sum; else shasum -a 1; fi; }

slug=$(clean "${1:-}")
[ -n "$slug" ] || { echo "usage: task-dir.sh <task-slug> [path]" >&2; exit 2; }
dir=${2:-.}
root=${HWORKS_TASKS_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/agent-tasks}

branch=
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
  bdir=$(clean "$branch")
  lossless "$branch" || bdir=$bdir+$(printf '%s' "$branch" | sha1 | cut -c1-8)
  out="$root/$repo/$bdir/$slug"
  cwd=$top
else
  repo=_misc
  out="$root/_misc/$slug"
  cwd=$(cd "$dir" 2>/dev/null && pwd -P) || cwd=$dir
fi

mkdir -p "$(dirname "$out")"
# Only the caller whose mkdir creates the leaf writes .task, so concurrent calls cannot clobber it.
if mkdir "$out" 2>/dev/null; then
  printf 'created=%s\nrepo=%s\nbranch=%s\nslug=%s\ncwd=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$repo" "$branch" "$slug" "$cwd" > "$out/.task"
elif [ ! -d "$out" ]; then
  mkdir "$out"
fi
printf '%s\n' "$out"
