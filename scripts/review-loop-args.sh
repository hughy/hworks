#!/usr/bin/env bash
# Print the args JSON for workflows/review-loop.js.
# usage: review-loop-args.sh <brief> <gate> <base> <effort>
#   effort: quick (gate only), standard (1 reviewer), exhaustive (2 reviewers, second on the review2 slot)
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)

if [ $# -ne 4 ]; then sed -n '2,4p' "$0" >&2; exit 2; fi
brief=$1; gate=$2; base=$3; effort=$4

case "$effort" in
  quick) reviewers=0 ;;
  standard) reviewers=1 ;;
  exhaustive) reviewers=2 ;;
  *) echo "effort must be quick, standard or exhaustive, got: $effort" >&2; exit 2 ;;
esac

case "$brief" in
  /*) ;;
  *) brief="$(cd "$(dirname "$brief")" && pwd)/$(basename "$brief")" ;;
esac
[ -f "$brief" ] || echo "warning: brief file not found: $brief" >&2

review2=""
if [ "$reviewers" -eq 2 ]; then
  shown=$("$root/scripts/models.sh" show)
  review2=$(awk '$1=="review2" {print $2}' <<< "$shown")
  reviewer=$(awk '$1=="reviewer" {print $2}' <<< "$shown")
  if [ "$review2" = "(session" ]; then review2=""; fi
  if [ "$reviewer" = "(session" ]; then reviewer=""; fi
  if [ "$review2" = "$reviewer" ]; then
    echo "warning: review2 slot matches the reviewer model (${reviewer:-session model}); both reviews run on one model" >&2
  fi
fi

node -e '
  const [brief, gate, base, reviewers, review2, rubricDir] = process.argv.slice(1);
  const args = { brief, gate, base, reviewers: Number(reviewers), rubricDir };
  if (review2) args.review2Model = review2;
  process.stdout.write(JSON.stringify(args) + "\n");
' "$brief" "$gate" "$base" "$reviewers" "$review2" "$root/skills/interrogate/references"
