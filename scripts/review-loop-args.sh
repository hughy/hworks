#!/usr/bin/env bash
# Print the args JSON for workflows/review-loop.js.
# usage: review-loop-args.sh <brief> <gate> <base> <effort> [worktree [task-dir]]
#   base: a ref; emitted as the merge-base SHA of it and the worktree's HEAD, or, when task-dir
#     holds a review ledger (scripts/review-range.py), as the furthest commit it covers
#   effort: quick (gate only, coder at :low), standard (1 reviewer), exhaustive (2 reviewers, coder on the exhaustive slot)
#   worktree: where the children run (default: the current directory); emitted as cwd when given
#   task-dir: directory for each child's output file (created if missing); emitted as an absolute taskDir when given
#   env GATE_TIMEOUT_MS: host gate timeout in ms, emitted as gateTimeoutMs when set (workflow default: 2400000, 40 minutes, covering a typical heavy-slot queue wait plus a full gate); projects with longer gates set GATE_TIMEOUT_MS.
#   env HWORKS_WORKFLOW_RUNTIME=codex: leave model selection to Codex instead of reading the pi model profile
# The gate is emitted wrapped in scripts/heavy.py, so the coder's, the host's, and each reviewer's gate runs share
# the host's heavy-job slots with every other loop on the machine; HWORKS_HEAVY_SLOTS=0 at run time turns that off.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)

if [ $# -lt 4 ] || [ $# -gt 6 ]; then sed -n '2,11p' "$0" >&2; exit 2; fi
brief=$1; gate=$2; base=$3; effort=$4; worktree=${5:-}; task_dir=${6:-}

case "$effort" in
  quick) reviewers=0 ;;
  standard) reviewers=1 ;;
  exhaustive) reviewers=2 ;;
  *) echo "effort must be quick, standard or exhaustive, got: $effort" >&2; exit 2 ;;
esac

gate_timeout=${GATE_TIMEOUT_MS:-}
if [ -n "$gate_timeout" ] && ! [[ "$gate_timeout" =~ ^[1-9][0-9]*$ ]]; then
  echo "GATE_TIMEOUT_MS must be a positive integer (milliseconds), got: $gate_timeout" >&2; exit 2
fi

case "$brief" in
  /*) ;;
  *) brief="$(cd "$(dirname "$brief")" && pwd)/$(basename "$brief")" ;;
esac
[ -f "$brief" ] || echo "warning: brief file not found: $brief" >&2

if [ -n "$worktree" ]; then
  worktree=$(cd "$worktree" && pwd -P)
fi
if [ -n "$task_dir" ]; then
  mkdir -p "$task_dir"
  task_dir=$(cd "$task_dir" && pwd -P)
fi
if ! base_sha=$(git -C "${worktree:-.}" merge-base "$base" HEAD 2>/dev/null); then
  echo "cannot resolve the merge-base of $base and HEAD in ${worktree:-$PWD}" >&2
  exit 2
fi
if [ -n "$task_dir" ] && [ -f "$task_dir/reviewed.tsv" ]; then
  # Exit 3 means HEAD is covered: the reviewers then read only the coder's new commits.
  rc=0
  covered=$(python3 "$root/scripts/review-range.py" base "$task_dir" "$base" --cwd "${worktree:-.}") || rc=$?
  if [ "$rc" -ne 0 ] && [ "$rc" -ne 3 ]; then
    echo "review-range.py base failed ($rc); not starting from the review ledger" >&2
    exit 2
  fi
  base_sha=$covered
fi

session=""
if [ -n "${PI_PROVIDER:-}" ] && [ -n "${PI_MODEL:-}" ]; then session="$PI_PROVIDER/$PI_MODEL"; fi

runtime=${HWORKS_WORKFLOW_RUNTIME:-pi}
shown=""
if [ "$runtime" != codex ]; then shown=$("$root/scripts/models.sh" show); fi
# Prints the role's or slot's model; a session-model entry prints the session model, or nothing when unknown.
model_of() {
  local m
  m=$(awk -v r="$1" '$1==r {print $2}' <<< "$shown")
  if [ "$m" = "(session" ]; then m=$session; fi
  printf '%s' "$m"
}

bare() { sed -E 's/:(off|minimal|low|medium|high|xhigh|max)$//' <<< "$1"; }

coder_model=""
case "$runtime:$effort" in
  pi:quick)
    coder_model=$(model_of coder)
    if [ -n "$coder_model" ]; then
      coder_model="$(bare "$coder_model"):low"
    else
      echo "warning: coder runs on the session model and PI_PROVIDER/PI_MODEL are unset; quick effort runs it without :low" >&2
    fi
    ;;
  pi:exhaustive)
    coder_model=$(model_of exhaustive)
    if [ -z "$coder_model" ]; then
      echo "warning: exhaustive slot is the session model and PI_PROVIDER/PI_MODEL are unset; coder runs on its role default" >&2
    fi
    ;;
esac

review2=""
if [ "$runtime" != codex ] && [ "$reviewers" -eq 2 ]; then
  review2=$(model_of review2)
  reviewer=$(model_of reviewer)
  if [ -z "$review2" ]; then
    echo "warning: review2 slot is the session model and PI_PROVIDER/PI_MODEL are unset; the second reviewer runs on the reviewer model" >&2
  fi
  if [ "$(bare "${review2:-$reviewer}")" = "$(bare "$reviewer")" ]; then
    echo "warning: review2 runs the reviewer model (${reviewer:-session model}); both reviews run on one model" >&2
  fi
fi

node -e '
  const [brief, rawGate, base, reviewers, review2, coderModel, cwd, rubricDir, taskDir, gateTimeout, preRead, heavy] = process.argv.slice(1);
  const q = (s) => "\x27" + s.replace(/\x27/g, "\x27\\\x27\x27") + "\x27";
  // A bare path keeps gate-timeout.ts able to see heavy.py; it cannot see inside quotes.
  const gate = "python3 " + (/^[\w.\/-]+$/.test(heavy) ? heavy : q(heavy)) + " sh -c " + q(rawGate);
  const args = { brief, gate, base, reviewers: Number(reviewers), rubricDir, preRead };
  if (review2) args.review2Model = review2;
  if (coderModel) args.coderModel = coderModel;
  if (cwd) args.cwd = cwd;
  if (taskDir) args.taskDir = taskDir;
  if (gateTimeout) args.gateTimeoutMs = Number(gateTimeout);
  process.stdout.write(JSON.stringify(args) + "\n");
' "$brief" "$gate" "$base_sha" "$reviewers" "$review2" "$coder_model" "$worktree" "$root/skills/interrogate/references" "$task_dir" "$gate_timeout" "$root/scripts/review-pre-read.py" "$root/scripts/heavy.py"
