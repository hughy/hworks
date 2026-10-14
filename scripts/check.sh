#!/usr/bin/env bash
# Runs the full hworks check with each part as its own process, up to CHECK_JOBS at once.
# CHECK_ROOT overrides the repo root (its scripts/, workflows/, and extensions/ are checked).
set -u

root=${CHECK_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
jobs_cap=${CHECK_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)}
case $jobs_cap in '' | *[!0-9]* | 0) echo "check.sh: CHECK_JOBS must be a positive integer" >&2; exit 2 ;; esac

out=$(mktemp -d "${TMPDIR:-/tmp}/hworks-check.XXXXXX") || exit 2
pids=()
cleanup() {
  for p in ${pids[@]+"${pids[@]}"}; do kill "$p" 2>/dev/null; done
  rm -rf "$out"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

names=()
dirs=()
cmds=()
add() { names+=("$1"); dirs+=("$2"); cmds+=("$3"); }

for f in "$root"/scripts/test_*.py; do
  [ -e "$f" ] || continue
  m=$(basename "$f" .py)
  add "py:$m" "$root/scripts" "python3 -m unittest $m"
done
set -- "$root"/workflows/*.test.js
if [ -e "$1" ]; then
  add "node:workflows" "$root" "node --test workflows/*.test.js"
fi
for f in "$root"/extensions/*.test.mts; do
  [ -e "$f" ] || continue
  add "mts:$(basename "$f" .test.mts)" "$root" "node --experimental-strip-types extensions/$(basename "$f")"
done

if [ ${#names[@]} -eq 0 ]; then
  echo "check.sh: no checks found under $root" >&2
  exit 2
fi

running() { jobs -rp | wc -l | tr -d ' '; }

i=0
while [ $i -lt ${#names[@]} ]; do
  while [ "$(running)" -ge "$jobs_cap" ]; do sleep 0.1; done
  (
    cd "${dirs[$i]}" || exit 1
    TIMEFORMAT=%R
    { time sh -c "${cmds[$i]}" >"$out/$i.log" 2>&1 </dev/null; } 2>"$out/$i.time"
    echo $? >"$out/$i.rc"
  ) &
  pids+=($!)
  i=$((i + 1))
done
for p in "${pids[@]}"; do wait "$p"; done

failed=0
i=0
while [ $i -lt ${#names[@]} ]; do
  rc=$(cat "$out/$i.rc" 2>/dev/null)
  t=$(tail -n 1 "$out/$i.time" 2>/dev/null)
  if [ "$rc" = 0 ]; then
    printf 'ok    %-28s %ss\n' "${names[$i]}" "${t:-?}"
  else
    failed=$((failed + 1))
    printf 'FAIL  %-28s %ss (exit %s)\n' "${names[$i]}" "${t:-?}" "${rc:-missing}"
  fi
  i=$((i + 1))
done

i=0
while [ $i -lt ${#names[@]} ]; do
  if [ "$(cat "$out/$i.rc" 2>/dev/null)" != 0 ]; then
    echo
    echo "===== ${names[$i]}: ${cmds[$i]} ====="
    cat "$out/$i.log" 2>/dev/null
  fi
  i=$((i + 1))
done

if [ $failed -ne 0 ]; then
  echo
  echo "check.sh: $failed of ${#names[@]} parts failed"
  exit 1
fi
echo "check.sh: all ${#names[@]} parts passed"
