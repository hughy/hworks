#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd -P)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/hoffice-instance.XXXXXX")
tmp=$(cd "$tmp" && pwd -P)
trap 'rm -rf "$tmp"' EXIT
export HOME="$tmp/home"
export HOFFICE_CONFIG_DIR="$tmp/config"
export HOFFICE_SKILLS_DIR="$tmp/skills"
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
unset HOFFICE_DIR HOFFICE_HOME
mkdir -p "$HOME" "$HOFFICE_CONFIG_DIR"

fail() { echo "FAIL: $1" >&2; exit 1; }
equal() { [ "$1" = "$2" ] || fail "$3: expected [$2], got [$1]"; }
reject() {
  local rc=0
  "$@" >"$tmp/out" 2>"$tmp/err" || rc=$?
  equal "$rc" 1 "failure exit for $*"
  [ ! -s "$tmp/out" ] || fail "failure printed stdout for $*"
  [ -s "$tmp/err" ] || fail "failure missing diagnostic for $*"
}

reject "$root/scripts/hoffice-instances.sh"
# Exercise both an empty registry and a registry with no final newline.
printf '\n\n' > "$HOFFICE_CONFIG_DIR/instances"
reject "$root/scripts/hoffice-instances.sh"

first="$tmp/first instance"
second="$tmp/second"
cp -R "$root/templates/instance" "$first"
cp -R "$root/templates/instance" "$second"
mkdir -p "$first/projects/hworks" "$first/projects/shared" "$second/projects/personal"
cat > "$first/repos/hughy--hworks.md" <<'CARD'
| Origin | `https://github.com/hughy/hworks` |
| Projects | `projects/hworks/`, `projects/shared/`, `projects/hworks/` |
CARD
cat > "$second/repos/hughy--hworks.md" <<'CARD'
| Origin | `ssh://git@code.example.org/hughy/hworks.git` |
| Projects | `projects/personal/` |
CARD

printf '%s' "$first" > "$HOFFICE_CONFIG_DIR/instances"
equal "$("$root/scripts/hoffice-instances.sh")" "$first" "single discovery"
repo="$tmp/checkout"
git init -q "$repo"
reject "$root/scripts/hoffice-project-for-repo.sh" "$repo"
grep -q 'no git origin' "$tmp/err" || fail "missing origin diagnostic"
git -C "$repo" remote add origin https://github.com/hughy/hworks.git
expected=$(printf '%s\thworks\n%s\tshared' "$first" "$first")
equal "$("$root/scripts/hoffice-project-for-repo.sh" "$repo")" "$expected" "https lookup and multiple projects"
for origin in git@github.com:hughy/hworks.git ssh://git@code.example.org/hughy/hworks https://code.example.org/hughy/hworks; do
  git -C "$repo" remote set-url origin "$origin"
  equal "$(cd "$repo" && "$root/scripts/hoffice-project-for-repo.sh")" "$expected" "origin normalization and default cwd"
done

# Copy the installer into a scratch engine to test missing and populated launchers.
engine="$tmp/engine"
mkdir -p "$engine/scripts"
cp "$root/scripts/install.sh" "$engine/scripts/"
"$engine/scripts/install.sh"
equal "$(cat "$HOFFICE_CONFIG_DIR/home")" "$engine" "engine registration with no launchers"
[ -d "$HOFFICE_SKILLS_DIR" ] || fail "skills directory not created"
equal "$(ls -A "$HOFFICE_SKILLS_DIR")" '' "no bogus launcher from unmatched glob"
mkdir -p "$engine/launchers/hoffice-test"
printf 'test launcher\n' > "$engine/launchers/hoffice-test/SKILL.md"
(cd "$tmp" && "$engine/scripts/install.sh" 'first instance' second)
"$engine/scripts/install.sh" "$first" "$second" "$first/."
equal "$(cat "$HOFFICE_CONFIG_DIR/instances")" "$(printf '%s\n%s' "$first" "$second")" "idempotent absolute instance registration"
equal "$(readlink "$HOFFICE_SKILLS_DIR/hoffice-test")" "$engine/launchers/hoffice-test" "launcher symlink"
equal "$(cat "$HOFFICE_SKILLS_DIR/hoffice-test/SKILL.md")" 'test launcher' "installed launcher usable"

# Registration order, empty lines, and the final unterminated line must survive discovery.
printf '\n%s\n\n%s' "$first" "$second" > "$HOFFICE_CONFIG_DIR/instances"
equal "$("$root/scripts/hoffice-instances.sh")" "$(printf '%s\n%s' "$first" "$second")" "multiple discovery"
expected=$(printf '%s\thworks\n%s\tshared\n%s\tpersonal' "$first" "$first" "$second")
equal "$("$root/scripts/hoffice-project-for-repo.sh" "$repo")" "$expected" "lookup across instances"

git -C "$repo" remote set-url origin https://github.com/example/unregistered.git
rc=0
"$root/scripts/hoffice-project-for-repo.sh" "$repo" >"$tmp/out" 2>"$tmp/err" || rc=$?
equal "$rc" 1 "no-match exit"
[ ! -s "$tmp/out" ] && [ ! -s "$tmp/err" ] || fail "no match must be silent"
git -C "$repo" remote set-url origin git@github.com:hughy/hworks.git

missing="$tmp/not-an-instance"
mkdir "$missing"
reject "$engine/scripts/install.sh" "$missing"
grep -q 'HOFFICE.md' "$tmp/err" || fail "installer missing marker diagnostic"
printf '%s\n%s\n' "$first" "$missing" > "$HOFFICE_CONFIG_DIR/instances"
reject "$root/scripts/hoffice-instances.sh"
grep -q 'HOFFICE.md' "$tmp/err" || fail "discovery missing marker diagnostic"
reject "$root/scripts/hoffice-project-for-repo.sh" "$repo"
export HOFFICE_DIR="$second"
equal "$("$root/scripts/hoffice-instances.sh")" "$second" "override ignores registry"
equal "$("$root/scripts/hoffice-project-for-repo.sh" "$repo")" "$(printf '%s\tpersonal' "$second")" "lookup override"
export HOFFICE_DIR="$missing"
reject "$root/scripts/hoffice-instances.sh"
unset HOFFICE_DIR
printf '' > "$HOFFICE_CONFIG_DIR/instances"
reject "$root/scripts/hoffice-project-for-repo.sh" "$repo"
grep -q 'no instance configured' "$tmp/err" || fail "lookup missing config diagnostic"

# Never replace a real file or directory with a launcher link.
mkdir -p "$engine/launchers/hoffice-occupied" "$HOFFICE_SKILLS_DIR/hoffice-occupied"
printf 'keep\n' > "$HOFFICE_SKILLS_DIR/hoffice-occupied/content"
reject "$engine/scripts/install.sh" "$first"
equal "$(cat "$HOFFICE_SKILLS_DIR/hoffice-occupied/content")" keep "installer preserves existing data"
echo 'ok: instance discovery, lookup, and installation'
