#!/usr/bin/env bash
set -uo pipefail

if [ "$#" -ne 1 ]; then
  echo 'usage: check-instance.sh <instance root>' >&2
  exit 2
fi
command -v awk >/dev/null || { echo 'check-instance.sh: awk is required' >&2; exit 2; }
engine=$(cd "${BASH_SOURCE[0]%/*}/.." && pwd -P) || exit 2
instance=$(cd "$1" 2>/dev/null && pwd -P) || { echo "check-instance.sh: cannot read instance root: $1" >&2; exit 2; }
[ -f "$instance/HOFFICE.md" ] || { echo 'HOFFICE.md: required instance marker is missing' >&2; exit 2; }
for template in published.md retro.md digest-config.md DOCS.md; do
  [ -r "$engine/templates/$template" ] || { echo "check-instance.sh: cannot read templates/$template" >&2; exit 2; }
done
cd "$instance" || exit 2
shopt -s nullglob dotglob
status=0
finding() { printf '%s: %s\n' "$1" "$2"; [ "$status" -eq 2 ] || status=1; }
checked() {
  local rc=0
  "$@" || rc=$?
  if [ "$rc" -gt 1 ]; then status=2; elif [ "$rc" -eq 1 ] && [ "$status" -eq 0 ]; then status=1; fi
}
project_names=''
for project in projects/*/; do project_names+="${project#projects/}"; done

# shellcheck disable=SC2329
frontmatter() {
  local file=$1 template=$2 field=$3 expected=$4
  awk -v field="$field" -v expected="$expected" -v projects="$project_names" '
    function report(message) { print ARGV[1] ": " message; failed=1 }
    function scalar(value) {
      sub(/[ \t]+#.*/, "", value)
      sub(/^[ \t]+/, "", value); sub(/[ \t\r]+$/, "", value)
      if (value ~ /^\042.*\042$/ || value ~ /^\047.*\047$/) value=substr(value, 2, length(value)-2)
      return value
    }
    function reference(value) {
      value=scalar(value)
      if (!(value in existing)) report("projects[].name \047" value "\047 does not exist under projects/")
    }
    BEGIN { n=split(projects, names, "/"); for (i=1; i<=n; i++) if (names[i]!="") existing[names[i]]=1 }
    FNR==1 { open=($0 ~ /^---\r?$/); closed=0; in_projects=0; next }
    !open || closed { next }
    /^---\r?$/ { closed=1; if (FILENAME==ARGV[1]) valid=1; next }
    match($0, /^([A-Za-z_][A-Za-z0-9_-]*|\042([^\042\\]|\\.)*\042|\047([^\047]|\047\047)*\047)[ \t]*:/) {
      key=substr($0, 1, RLENGTH); sub(/[ \t]*:$/, "", key)
      sub(/[ \t]+$/, "", key)
      if (key ~ /^[\042\047]/) key=substr(key, 2, length(key)-2)
      value=substr($0, RLENGTH+1)
      if (FILENAME==ARGV[1]) {
        actual[key]=1; values[key]=scalar(value)
        in_projects=(key=="projects")
      } else if (FILENAME==ARGV[2]) standard[key]=1
      else retro[key]=1
    }
    FILENAME==ARGV[1] && in_projects {
      rest=$0
      while (match(rest, /[\042\047]?name[\042\047]?[ \t]*:/)) {
        rest=substr(rest, RSTART+RLENGTH)
        value=rest; sub(/[,}\]].*$/, "", value)
        reference(value)
      }
    }
    END {
      if (!valid) report("frontmatter must open and close with ---")
      if (field=="name") {
        if (!(field in actual) || values[field]=="" || values[field]=="null" || values[field]=="~") report("frontmatter requires a nonempty name")
      } else {
        use_retro=(field=="project" && values["type"]=="retrospective")
        for (key in standard) if (!use_retro && !(key in actual)) report("missing frontmatter key: " key)
        for (key in retro) if (use_retro && !(key in actual)) report("missing frontmatter key: " key)
        for (key in actual) if ((use_retro && !(key in retro)) || (!use_retro && !(key in standard))) report("unknown frontmatter key: " key)
        if (values[field]!=expected) report(field " must equal \047" expected "\047 (found \047" values[field] "\047)")
      }
      exit failed ? 1 : 0
    }
  ' "$file" "$template" "$engine/templates/retro.md"
}
checked frontmatter HOFFICE.md /dev/null name ''

access_extension=extensions/access.md
[ -f "$access_extension" ] || access_extension=/dev/null
for project in projects/*/; do
  name=${project#projects/}; name=${name%/}
  for required in README.md STATE.md DOCS.md; do
    [ -f "$project$required" ] || finding "$project$required" 'required project file is missing'
  done
  for file in "$project"published/*.md; do
    [ "${file##*/}" = README.md ] && continue
    checked frontmatter "$file" "$engine/templates/published.md" project "$name"
  done
  [ -f "${project}DOCS.md" ] || continue
  # shellcheck disable=SC2016
  checked awk '
    function cell(value) { gsub(/\140/, "", value); sub(/^[ \t]+/, "", value); sub(/[ \t\r]+$/, "", value); return value }
    function columns(line, cols,    count, i, c, found) {
      for (i in cols) delete cols[i]
      found=sub(/^[ \t]*\|/, "", line)
      count=1; cols[count]=""
      for (i=1; i<=length(line); i++) {
        c=substr(line, i, 1)
        if (c=="\\" && substr(line, i+1, 1)=="|") { cols[count]=cols[count] "|"; i++ }
        else if (c=="|") { found=1; count++; cols[count]="" }
        else cols[count]=cols[count] c
      }
      if (count>1 && cols[count] ~ /^[ \t\r]*$/) count--
      return found ? count : 0
    }
    FNR==1 { access=0; table=0; value_column=0 }
    {
      count=columns($0, cols)
      if (!count) { table=0; access=0; value_column=0; next }
      if (FILENAME!=ARGV[3]) {
        if (!table) {
          table=1
          if (FILENAME==ARGV[2]) value_column=1
          else for (i=1; i<=count; i++) if (cell(cols[i])=="Value") value_column=i
          next
        }
        if (!value_column) next
        n=split(cell(cols[value_column]), values, ",")
        for (i=1; i<=n; i++) {
          value=cell(values[i])
          if (value!="" && value !~ /^:?-+:?$/) allowed[value]=1
        }
        next
      }
      for (i=1; i<=count; i++) if (cell(cols[i])=="Agent access") { access=i; next }
      if (!access) next
      value=cell(cols[access])
      if (value ~ /^:?-+:?$/) next
      n=split(value, values, ",")
      for (i=1; i<=n; i++) {
        value=cell(values[i])
        if (value!="" && !(value in allowed)) {
          print FILENAME ": unknown Agent access value: " value " (expected an engine value or extensions/access.md value)"
          failed=1
        }
      }
    }
    END { exit failed ? 1 : 0 }
  ' "$engine/templates/DOCS.md" "$access_extension" "${project}DOCS.md"
done
for file in digests/*/DIGEST.md; do
  name=${file#digests/}; name=${name%/DIGEST.md}
  checked frontmatter "$file" "$engine/templates/digest-config.md" digest "$name"
done
for directory in procedures launchers templates; do
  [ ! -d "$directory" ] || finding "$directory/" 'engine directory must not be copied into an instance'
done
for file in scripts/render-digest.mjs scripts/render-published.mjs; do
  [ ! -e "$file" ] || finding "$file" 'engine renderer must not be copied into an instance'
done
for file in repos/*--*.md; do
  # shellcheck disable=SC2016
  checked awk -F '|' '
    function cell(value) { gsub(/\140/, "", value); sub(/^[ \t]+/, "", value); sub(/[ \t\r]+$/, "", value); return value }
    cell($2)=="Origin" { origin=1 }
    cell($2)=="Projects" { projects=1; if ($3 !~ /projects\/[^\/]+\//) invalid=1 }
    END {
      if (!origin) print FILENAME ": missing Origin row"
      if (!projects) print FILENAME ": missing Projects row"
      if (invalid) print FILENAME ": Projects row must contain projects/<name>/ paths"
      exit (!origin || !projects || invalid) ? 1 : 0
    }
  ' "$file"
  references=$(awk -F '|' '
    $2 ~ /^[ \t]*\140?Projects\140?[ \t]*$/ {
      rest=$3
      while (match(rest, /projects\/[^\/\140 ,|]+\//)) {
        print substr(rest, RSTART, RLENGTH); rest=substr(rest, RSTART+RLENGTH)
      }
    }
  ' "$file") || { status=2; continue; }
  while IFS= read -r reference; do
    [ -z "$reference" ] || [ -d "$reference" ] || finding "$file" "Projects path does not exist: $reference"
  done <<< "$references"
done
exit "$status"
