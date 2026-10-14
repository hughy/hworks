#!/usr/bin/env bash
# Stands in for review-loop-args.sh in orchestrate tests: the same args JSON without models.sh or node.
# usage: fake-review-loop-args.sh <brief> <gate> <base> <effort> [worktree [task-dir]]
set -euo pipefail
brief=$1; gate=$2; base=$3; effort=$4; worktree=${5:-}; task_dir=${6:-}
case "$effort" in
  quick) reviewers=0 ;;
  standard) reviewers=1 ;;
  exhaustive) reviewers=2 ;;
  *) echo "effort must be quick, standard or exhaustive, got: $effort" >&2; exit 2 ;;
esac
if [ -n "$worktree" ]; then worktree=$(cd "$worktree" && pwd -P); fi
base_sha=$(git -C "${worktree:-.}" merge-base "$base" HEAD)
root=$(cd "$(dirname "$0")/../.." && pwd)
q() { local s=${1//\\/\\\\}; s=${s//\"/\\\"}; printf '"%s"' "$s"; }
printf '{"base": %s, "brief": %s, "gate": %s, "reviewers": %d, "rubricDir": %s' \
  "$(q "$base_sha")" "$(q "$brief")" "$(q "$gate")" "$reviewers" "$(q "$root/skills/interrogate/references")"
if [ -n "$worktree" ]; then printf ', "cwd": %s' "$(q "$worktree")"; fi
if [ -n "$task_dir" ]; then mkdir -p "$task_dir"; printf ', "taskDir": %s' "$(q "$(cd "$task_dir" && pwd -P)")"; fi
printf '}\n'
