#!/bin/sh
# Stands in for gh in test_kaizen_prs.py and test_kaizen_prep.py.
dir=$(dirname "$0")
case "$1 $2" in
"auth status")
  if [ "$3" = --active ]; then cat "$dir/auth-status.txt"; else cat "$dir/auth-status-all.txt"; fi
  exit 1
  ;;
"pr view")
  case "$3" in
  https://github.com/acme/app/pull/*)
    cat "$dir/pr-${3##*/}.json"
    ;;
  *)
    echo "error connecting to ${3#https://}" | cut -d/ -f1 >&2
    echo "second line" >&2
    exit 1
    ;;
  esac
  ;;
esac
