#!/usr/bin/env bash
# Flags stale mux worktrees and old forge/anvil state; with --delete, removes them and clears go and npm caches.
# MUX_ROOT (default ~/.mux), FOUNDRY_ROOT (default ~/.foundry), and STALE_DAYS (default 3) override the defaults.
set -u

mux_root=${MUX_ROOT:-$HOME/.mux}
foundry_root=${FOUNDRY_ROOT:-$HOME/.foundry}
days=${STALE_DAYS:-3}
delete=0
[ "${1:-}" = --delete ] && delete=1
here=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

worktrees=()
# A linked worktree has a .git file; main checkouts have a .git directory and are never flagged.
while IFS= read -r gitfile; do
  wt=${gitfile%/.git}
  [ "$wt" = "$here" ] && continue
  read -r line < "$gitfile"
  gitdir=${line#gitdir: }
  [ -d "$gitdir" ] || continue
  if [ -z "$(find "$gitdir" "$wt" -name node_modules -prune -o -mtime -"$days" -print -quit 2>/dev/null)" ]; then
    worktrees+=("$wt")
  fi
done < <(find "$mux_root" -maxdepth 4 -name .git -type f 2>/dev/null)

state=()
for d in "$foundry_root/anvil/tmp" "$foundry_root/cache/rpc"; do
  [ -d "$d" ] || continue
  while IFS= read -r p; do state+=("$p"); done < <(find "$d" -mindepth 1 -maxdepth 1 -mtime +"$days" 2>/dev/null)
done

echo "Stale worktrees (no change in ${days}+ days):"
for p in ${worktrees[@]+"${worktrees[@]}"}; do echo "  $(du -sh "$p" 2>/dev/null | cut -f1)	$p"; done
echo "Old forge/anvil state:"
for p in ${state[@]+"${state[@]}"}; do echo "  $(du -sh "$p" 2>/dev/null | cut -f1)	$p"; done

if [ "$delete" -eq 0 ]; then
  echo "Dry run. Rerun with --delete to remove the above and clear go and npm caches."
  exit 0
fi

df -h "$HOME" | tail -1 | awk '{print "Free before: " $4}'
kept=()
for wt in ${worktrees[@]+"${worktrees[@]}"}; do
  # No --force: git refuses a worktree with uncommitted or untracked files. Its branch is kept.
  common=$(git -C "$wt" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
  if git -C "$wt" worktree remove "$wt" 2>/dev/null; then
    [ -n "$common" ] && git --git-dir="$common" worktree prune 2>/dev/null
  else
    kept+=("$wt")
  fi
done
for p in ${state[@]+"${state[@]}"}; do rm -rf "$p"; done
command -v go >/dev/null && go clean -cache -testcache -modcache
command -v npm >/dev/null && npm cache clean --force 2>/dev/null
df -h "$HOME" | tail -1 | awk '{print "Free after:  " $4}'
if [ ${#kept[@]} -gt 0 ]; then
  echo "Kept (uncommitted or untracked changes):"
  for p in "${kept[@]}"; do echo "  $p"; done
fi
