#!/usr/bin/env bash
# Print the configured instance roots, one absolute path per line.
set -euo pipefail

config=${HOFFICE_CONFIG_DIR:-"$HOME/.config/hoffice"}
if [ -n "${HOFFICE_DIR:-}" ]; then
  roots=$HOFFICE_DIR
elif [ -f "$config/instances" ]; then
  roots=$(cat "$config/instances")
else
  roots=''
fi

found=0
while IFS= read -r instance; do
  [ -n "$instance" ] || continue
  if [ ! -f "$instance/HOFFICE.md" ]; then
    echo "hoffice-instances: missing HOFFICE.md in $instance" >&2
    exit 1
  fi
  found=1
done <<< "$roots"
if [ "$found" = 0 ]; then
  echo "hoffice-instances: no instance configured; run install.sh or set HOFFICE_DIR" >&2
  exit 1
fi

while IFS= read -r instance; do
  [ -n "$instance" ] || continue
  (cd "$instance" && pwd -P)
done <<< "$roots"
