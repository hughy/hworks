#!/usr/bin/env bash
# Match a checkout's origin to repo cards in every configured instance.
# Print <instance root><TAB><project name> per match; no match exits 1 silently.
set -euo pipefail

engine=$(cd "$(dirname "$0")/.." && pwd)
repo=${1:-.}
origin=$(git -C "$repo" remote get-url origin 2>/dev/null || true)
if [ -z "$origin" ]; then
  echo "hoffice-project-for-repo: no git origin in $repo" >&2
  exit 1
fi
instances=$("$engine/scripts/hoffice-instances.sh") || exit 1

# The final two path components identify a repo across hosts and clone protocols.
normalize() {
  printf '%s\n' "$1" | sed -E 's#\.git$##; s#^.*[:/]([^/:]+/[^/]+)$#\1#'
}
slug=$(normalize "$origin")
found=0
while IFS= read -r instance; do
  for card in "$instance"/repos/*--*.md; do
    [ -f "$card" ] || continue
    # shellcheck disable=SC2016
    card_origin=$(sed -nE '/^\| Origin \|/s/.*`([^`]+)`.*/\1/p' "$card")
    [ "$(normalize "$card_origin")" = "$slug" ] || continue
    projects=$(sed -nE '/^\| Projects \|/p' "$card" | grep -oE 'projects/[A-Za-z0-9._-]+/' | sort -u || true)
    while IFS= read -r project; do
      [ -n "$project" ] || continue
      project=${project#projects/}
      project=${project%/}
      printf '%s\t%s\n' "$instance" "$project"
      found=1
    done <<< "$projects"
  done
done <<< "$instances"
[ "$found" = 1 ] || exit 1
