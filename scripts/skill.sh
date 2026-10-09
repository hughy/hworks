#!/usr/bin/env bash
# Manage the allowlist of pstack skills that hworks exposes.
# usage: skill.sh enable <name> [reason]
#        skill.sh disable <name> [reason]
#        skill.sh list
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
skills="$root/skills"
src="$root/pstack/skills"
div="$root/DIVERGENCE.md"
upstream=$(git -C "$root" log -1 --grep "^git-subtree-dir: pstack" --format=%B 2>/dev/null | sed -n "s/^git-subtree-split: \(.......\).*/\1/p"); upstream=${upstream:-unknown}

cmd=${1:-}; name=${2:-}; reason=${3:-}

ensure_div() {
  [ -f "$div" ] && return
  printf '# Divergence from pstack\n\nOne line per pstack skill or principle that hworks does not link. `scripts/skill.sh enable <name>` removes a line; `disable` adds one.\n\n| skill | reason | mirror commit |\n|---|---|---|\n' > "$div"
}

case "$cmd" in
  enable)
    [ -n "$name" ] || { echo "usage: skill.sh enable <name>" >&2; exit 2; }
    [ -d "$src/$name" ] || { echo "no pstack skill named $name under $src" >&2; exit 1; }
    ln -sfn "../pstack/skills/$name" "$skills/$name"
    ensure_div
    grep -v "^| \`$name\` |" "$div" > "$div.tmp" && mv "$div.tmp" "$div"
    echo "linked $name. Run /reload in pi."
    ;;
  disable)
    [ -n "$name" ] || { echo "usage: skill.sh disable <name> [reason]" >&2; exit 2; }
    [ -d "$src/$name" ] || { echo "no pstack skill named $name under $src" >&2; exit 1; }
    rm -f "$skills/$name"
    ensure_div
    grep -v "^| \`$name\` |" "$div" > "$div.tmp" && mv "$div.tmp" "$div"
    printf '| `%s` | %s | %s |\n' "$name" "${reason:-not linked}" "$upstream" >> "$div"
    echo "unlinked $name. Run /reload in pi."
    ;;
  list)
    for d in "$src"/*/; do
      n=$(basename "$d")
      if [ -L "$skills/$n" ]; then echo "linked    $n"; else echo "unlinked  $n"; fi
    done
    ;;
  *) sed -n '2,5p' "$0"; exit 2 ;;
esac
