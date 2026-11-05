#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd -P)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/hoffice-check-instance.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
checker="$root/scripts/check-instance.sh"
fail() { echo "FAIL: $1" >&2; exit 1; }
run() {
  local expected=$1 rc=0
  shift
  "$@" >"$tmp/out" 2>"$tmp/err" || rc=$?
  [ "$rc" -eq "$expected" ] || { cat "$tmp/out" "$tmp/err" >&2; fail "expected exit $expected, got $rc: $*"; }
}
contains() { grep -F -- "$1" "$tmp/out" >/dev/null || { cat "$tmp/out" >&2; fail "missing finding: $1"; }; }
set_key() {
  local file=$1 key=$2 value=$3
  awk -v key="$key" -v value="$value" 'index($0, key ":")==1 { print key ": " value; next } { print }' "$file" >"$tmp/edit"
  cp "$tmp/edit" "$file"
}
remove_key() {
  local file=$1 key=$2
  awk -v key="$key" 'index($0, key ":")!=1' "$file" >"$tmp/edit"
  cp "$tmp/edit" "$file"
}
valid="$tmp/valid instance"
mkdir -p "$valid/projects/sample/published" "$valid/digests/daily" "$valid/extensions" "$valid/repos"
cp "$root/templates/instance/HOFFICE.md" "$valid/HOFFICE.md"
cp "$root/templates/project-README.md" "$valid/projects/sample/README.md"
cp "$root/templates/project-STATE.md" "$valid/projects/sample/STATE.md"
cp "$root/templates/DOCS.md" "$valid/projects/sample/DOCS.md"
cp "$root/templates/published.md" "$valid/projects/sample/published/report.md"
cp "$root/templates/retro.md" "$valid/projects/sample/published/retro.md"
for file in "$valid"/projects/sample/published/*.md; do set_key "$file" project '"sample" # directory name'; done
cp "$root/templates/digest-config.md" "$valid/digests/daily/DIGEST.md"
set_key "$valid/digests/daily/DIGEST.md" digest "'daily'"
set_key "$valid/digests/daily/DIGEST.md" '  - name' sample
cat >"$valid/extensions/access.md" <<'ACCESS'
# Extra access

| Value | System | Tool | Fallback |
|---|---|---|---|
| `archive`, `vault` | Archive | File read | Ask |
ACCESS
cat >>"$valid/projects/sample/DOCS.md" <<'DOCS'

| Doc | Agent access | Notes |
|---|---|---|
| Example | `public`, archive, vault | Supported alternatives |
| Checkout | git, local, mirror | Engine values |
| Unset | | No access recorded |
DOCS
cp "$root/templates/repo-card.md" "$valid/repos/example--sample.md"
# Replace the template path while keeping the rest of the card current.
awk '{ gsub(/projects\/<name>\//, "projects/sample/"); print }' "$valid/repos/example--sample.md" >"$tmp/edit"
cp "$tmp/edit" "$valid/repos/example--sample.md"
for history in projects/sample/sessions/old.md projects/sample/decisions/old.md digests/daily/2020-01-01.md projects/sample/published/README.md; do
  mkdir -p "$valid/${history%/*}"
  printf '%s\n' '---' 'old_key: historical' '---' >"$valid/$history"
done
run 0 "$checker" "$valid"
[ ! -s "$tmp/out" ] && [ ! -s "$tmp/err" ] || fail 'valid instance must be silent'
# The access extension is optional when only engine values are used.
count=0
fresh() {
  count=$((count + 1)); instance="$tmp/case $count"
  cp -R "$valid" "$instance"
}
fresh
rm "$instance/extensions/access.md"
set_key "$instance/HOFFICE.md" name '"another instance"'
awk '{ gsub(/archive|vault/, "public"); print }' "$instance/projects/sample/DOCS.md" >"$tmp/edit"
cp "$tmp/edit" "$instance/projects/sample/DOCS.md"
run 0 "$checker" "$instance"

fresh
remove_key "$instance/HOFFICE.md" name
run 1 "$checker" "$instance"
contains 'HOFFICE.md: frontmatter requires a nonempty name'
for value in '' '""' "''" null '~'; do
  fresh
  set_key "$instance/HOFFICE.md" name "$value"
  run 1 "$checker" "$instance"
  contains 'HOFFICE.md: frontmatter requires a nonempty name'
done
fresh
printf 'name: outside frontmatter\n' >"$instance/HOFFICE.md"
run 1 "$checker" "$instance"
contains 'HOFFICE.md: frontmatter must open and close with ---'
for required in README.md STATE.md DOCS.md; do
  fresh
  rm "$instance/projects/sample/$required"
  run 1 "$checker" "$instance"
  contains "projects/sample/$required: required project file is missing"
done
for path in projects/sample/published/report.md projects/sample/published/retro.md digests/daily/DIGEST.md; do
  fresh
  file="$instance/$path"
  awk 'NR==2 { print "\042stale_key\042: true"; print "\047old_key\047: true" } { print }' "$file" >"$tmp/edit"
  cp "$tmp/edit" "$file"
  run 1 "$checker" "$instance"
  contains "$path: unknown frontmatter key: stale_key"
  contains "$path: unknown frontmatter key: old_key"
  fresh
  file="$instance/$path"
  awk '/^slug:|^digest:/ { sub(/:/, "\042:"); print "\042" $0; next } { print }' "$file" >"$tmp/edit"
  cp "$tmp/edit" "$file"
  run 0 "$checker" "$instance"
done
for document in report retro; do
  fresh
  file="$instance/projects/sample/published/$document.md"
  remove_key "$file" slug
  awk 'NR==2 { print "bdocs_slug: obsolete" } { print }' "$file" >"$tmp/edit"
  cp "$tmp/edit" "$file"
  run 1 "$checker" "$instance"
  contains "projects/sample/published/$document.md: missing frontmatter key: slug"
  contains "projects/sample/published/$document.md: unknown frontmatter key: bdocs_slug"
  fresh
  set_key "$instance/projects/sample/published/$document.md" project stale
  run 1 "$checker" "$instance"
  contains "projects/sample/published/$document.md: project must equal 'sample' (found 'stale')"
done
fresh
remove_key "$instance/projects/sample/published/retro.md" window
run 1 "$checker" "$instance"
contains 'projects/sample/published/retro.md: missing frontmatter key: window'
fresh
printf 'no frontmatter\n' >"$instance/projects/sample/published/report.md"
run 1 "$checker" "$instance"
contains 'projects/sample/published/report.md: frontmatter must open and close with ---'
contains 'projects/sample/published/report.md: missing frontmatter key: slug'

fresh
remove_key "$instance/digests/daily/DIGEST.md" cadence
set_key "$instance/digests/daily/DIGEST.md" digest wrong
set_key "$instance/digests/daily/DIGEST.md" '  - name' missing
awk 'NR==2 { print "old_key: obsolete" } { print }' "$instance/digests/daily/DIGEST.md" >"$tmp/edit"
cp "$tmp/edit" "$instance/digests/daily/DIGEST.md"
run 1 "$checker" "$instance"
contains 'digests/daily/DIGEST.md: missing frontmatter key: cadence'
contains 'digests/daily/DIGEST.md: unknown frontmatter key: old_key'
contains "digests/daily/DIGEST.md: digest must equal 'daily' (found 'wrong')"
contains "digests/daily/DIGEST.md: projects[].name 'missing' does not exist under projects/"
fresh
set_key "$instance/digests/daily/DIGEST.md" projects '[{"name":"missing"}]'
run 1 "$checker" "$instance"
contains "digests/daily/DIGEST.md: projects[].name 'missing' does not exist under projects/"
for table in \
  $'| Doc | Agent access |\n|---|---|\n| Bad | public, unknown |' \
  $'Doc | Agent access\n--- | ---\nUnset |\nBad | public, unknown' \
  $'| Doc | Agent access\n|---|---\n| Bad | public, unknown' \
  $'Doc | Agent access |\n---|---|\nBad | public, unknown |' \
  $'| Doc | Agent access |\n|---|---|\n| Example \\| public | unknown |' \
  $'Doc | Agent access\n---|---\nExample \\| public | unknown'; do
  fresh
  printf '\n%s\n' "$table" >>"$instance/projects/sample/DOCS.md"
  run 1 "$checker" "$instance"
  contains 'projects/sample/DOCS.md: unknown Agent access value: unknown'
done
fresh
printf '\nDoc | Agent access\n---|---\nExample \\| unknown | public\n' >>"$instance/projects/sample/DOCS.md"
printf 'Value | Notes\n---|---\narchive, vault | Read \\| ask\n' >"$instance/extensions/access.md"
run 0 "$checker" "$instance"
fresh
rm "$instance/extensions/access.md"
run 1 "$checker" "$instance"
contains 'projects/sample/DOCS.md: unknown Agent access value: archive'
for directory in procedures launchers templates; do
  fresh
  mkdir "$instance/$directory"
  run 1 "$checker" "$instance"
  contains "$directory/: engine directory must not be copied into an instance"
done
for renderer in render-digest.mjs render-published.mjs; do
  fresh
  mkdir "$instance/scripts"
  touch "$instance/scripts/$renderer"
  run 1 "$checker" "$instance"
  contains "scripts/$renderer: engine renderer must not be copied into an instance"
done
for row in Origin Projects; do
  fresh
  awk -F '|' -v row="$row" '$2 != " " row " "' "$instance/repos/example--sample.md" >"$tmp/edit"
  cp "$tmp/edit" "$instance/repos/example--sample.md"
  run 1 "$checker" "$instance"
  contains "repos/example--sample.md: missing $row row"
done
fresh
cat >>"$instance/repos/example--sample.md" <<'CARD'
| Projects | `projects/sample/`, `projects/missing/` |
CARD
run 1 "$checker" "$instance"
contains 'repos/example--sample.md: Projects path does not exist: projects/missing/'
fresh
awk -F '|' '$2 != " Projects "' "$instance/repos/example--sample.md" >"$tmp/edit"
cp "$tmp/edit" "$instance/repos/example--sample.md"
printf '| Projects | |\n' >>"$instance/repos/example--sample.md"
run 1 "$checker" "$instance"
contains 'repos/example--sample.md: Projects row must contain projects/<name>/ paths'

# A changed engine template must affect validation without updating the checker.
engine="$tmp/engine"
mkdir -p "$engine/scripts"
cp "$checker" "$engine/scripts/"
cp -R "$root/templates" "$engine/templates"
for template in published.md retro.md digest-config.md; do
  awk 'NR==2 { print "new_required_key: null" } { print }' "$engine/templates/$template" >"$tmp/edit"
  cp "$tmp/edit" "$engine/templates/$template"
done
run 1 "$engine/scripts/check-instance.sh" "$valid"
for file in projects/sample/published/report.md projects/sample/published/retro.md digests/daily/DIGEST.md; do
  contains "$file: missing frontmatter key: new_required_key"
done
cp -R "$root/templates/." "$engine/templates/"
awk '/^\| `public`/ { print "| `runtime-access` | Public web | File read | Ask |" } { print }' "$engine/templates/DOCS.md" >"$tmp/edit"
cp "$tmp/edit" "$engine/templates/DOCS.md"
fresh
printf '\n| Doc | Agent access |\n|---|---|\n| New | runtime-access |\n' >>"$instance/projects/sample/DOCS.md"
run 0 "$engine/scripts/check-instance.sh" "$instance"

mkdir "$tmp/not an instance"
run 2 "$checker" "$tmp/not an instance"
run 2 "$checker"
run 2 "$checker" "$valid" extra
run 2 env PATH="$tmp/not an instance" /bin/bash "$checker" "$valid"
grep -F 'awk is required' "$tmp/err" >/dev/null || fail 'missing tool diagnostic'
echo 'ok: instance validation and exit codes'
