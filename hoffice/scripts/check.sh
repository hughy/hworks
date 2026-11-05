#!/usr/bin/env bash
# The full hoffice check: every part runs, then the script exits non-zero if any failed.
# Scans tracked and untracked (not ignored) files, so it can run before a commit.
set -u

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root" || exit 2
if [ "$(git rev-parse --show-toplevel 2>/dev/null)" != "$(pwd -P)" ]; then
  echo "check.sh: $root is not the top of a git worktree; file discovery needs git" >&2
  exit 2
fi
command -v rg >/dev/null || { echo "check.sh: rg (ripgrep) is required" >&2; exit 2; }
listing=$(mktemp "${TMPDIR:-/tmp}/hoffice-check.XXXXXX") || exit 2
trap 'rm -f "$listing"' EXIT

failed=()
run() {
  local name=$1
  shift
  echo "== $name"
  if "$@"; then echo "ok   $name"; else echo "FAIL $name"; failed+=("$name"); fi
}

# files <pathspec...>: NUL-separated paths that exist. Exits the whole script if git fails,
# so a discovery error can never read as an empty, passing scan.
files() {
  git ls-files -z --cached --others --exclude-standard -- "$@" >"$listing" || { echo "check.sh: git ls-files failed" >&2; kill -TERM $$; exit 2; }
  local f
  while IFS= read -r -d '' f; do [ -f "$f" ] && printf '%s\0' "$f"; done <"$listing"
}

# The engine names no tracker, chat, or document system; instances supply those. Skips this file, which lists them.
neutral() {
  local hits rc=0 list=() f
  while IFS= read -r -d '' f; do list+=("$f"); done < <(files . ':!scripts/check.sh')
  [ ${#list[@]} -gt 0 ] || { echo "neutral: no files to scan" >&2; return 1; }
  hits=$(rg -n -i -w --no-config -e 'linear|slack|gdoc|google|jira|confluence|notion' -- "${list[@]}") || rc=$?
  [ $rc -eq 1 ] && return 0
  [ $rc -eq 0 ] || { echo "neutral: rg failed (exit $rc)" >&2; return 1; }
  echo "$hits" | head -20
  echo "Name the extension point (docs/extensions.md) instead of a specific system." >&2
  return 1
}

shell_files() {
  files . | while IFS= read -r -d '' f; do
    case $f in *.sh) printf '%s\0' "$f"; continue ;; esac
    head -n1 "$f" | grep -qE '^#!.*\b(ba)?sh\b' && printf '%s\0' "$f"
  done
}

shellcheck_all() {
  command -v shellcheck >/dev/null || { echo "shellcheck not installed" >&2; return 1; }
  local list=() f
  while IFS= read -r -d '' f; do list+=("$f"); done < <(shell_files)
  [ ${#list[@]} -gt 0 ] || { echo "no shell files found" >&2; return 1; }
  shellcheck "${list[@]}"
}

# Every SKILL.md has frontmatter whose name matches its directory and a description.
# Launchers are installed globally, so their names carry the hoffice- prefix.
skills() {
  local f dir name rc=0
  while IFS= read -r -d '' f; do
    dir=$(basename "$(dirname "$f")")
    if ! awk 'NR==1 && $0!="---"{exit 1} NR>1 && $0=="---"{closed=1; exit} END{exit !closed}' "$f"; then
      echo "$f: frontmatter must open and close with ---"; rc=1; continue
    fi
    name=$(awk 'NR==1 && $0!="---"{exit} NR>1 && $0=="---"{exit} NR>1 && /^name:/{sub(/^name:[ ]*/,""); print}' "$f")
    if [ "$name" != "$dir" ]; then echo "$f: name '$name' does not match directory '$dir'"; rc=1; fi
    if ! awk 'NR>1 && $0=="---"{exit} /^description: ./{found=1} END{exit !found}' "$f"; then
      echo "$f: missing description"; rc=1
    fi
    case $f in launchers/*) case $dir in hoffice-*) ;; *) echo "$f: launcher name must start with hoffice-"; rc=1 ;; esac ;; esac
  done < <(files 'procedures/*/SKILL.md' 'launchers/*/SKILL.md')
  return $rc
}

node_syntax() {
  local rc=0 f
  while IFS= read -r -d '' f; do node --check "$f" || rc=1; done < <(files '*.mjs' '*.js')
  return $rc
}

shell_tests() {
  local rc=0 n=0 f
  while IFS= read -r -d '' f; do
    echo "-- $f"
    n=$((n + 1))
    bash "$f" || rc=1
  done < <(files 'tests/*.test.sh')
  return $rc
}

node_tests() {
  local list=()
  while IFS= read -r -d '' f; do list+=("$f"); done < <(files 'tests/*.test.mjs')
  [ ${#list[@]} -eq 0 ] && return 0
  if [ ! -d node_modules/marked ] || [ ! -d node_modules/yaml ]; then
    npm ci --ignore-scripts || { echo "check.sh: npm ci failed; renderer tests need marked and yaml" >&2; return 1; }
  fi
  node --test "${list[@]}"
}

run neutral neutral
run shellcheck shellcheck_all
run skills skills
run node-syntax node_syntax
run shell-tests shell_tests
run node-tests node_tests

if [ ${#failed[@]} -gt 0 ]; then
  echo "check.sh: failed: ${failed[*]}" >&2
  exit 1
fi
echo "check.sh: all checks passed"
