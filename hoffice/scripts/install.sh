#!/usr/bin/env bash
# Usage: install.sh [instance...]
# HOFFICE_CONFIG_DIR and HOFFICE_SKILLS_DIR override the per-user install paths.
set -euo pipefail

engine=$(cd "$(dirname "$0")/.." && pwd -P)
config=${HOFFICE_CONFIG_DIR:-"$HOME/.config/hoffice"}
skills=${HOFFICE_SKILLS_DIR:-"$HOME/.agents/skills"}

for instance in "$@"; do
  if [ ! -f "$instance/HOFFICE.md" ]; then
    echo "install: missing HOFFICE.md in $instance" >&2
    exit 1
  fi
done
for launcher in "$engine"/launchers/*/; do
  [ -d "$launcher" ] || continue
  target="$skills/$(basename "$launcher")"
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    echo "install: refusing to replace $target; move it before installing" >&2
    exit 1
  fi
done

mkdir -p "$config" "$skills"
printf '%s\n' "$engine" > "$config/home"
touch "$config/instances"
for instance in "$@"; do
  instance=$(cd "$instance" && pwd -P)
  if ! grep -Fxq -- "$instance" "$config/instances"; then
    if [ -s "$config/instances" ] && [ -n "$(tail -c 1 "$config/instances")" ]; then
      printf '\n' >> "$config/instances"
    fi
    printf '%s\n' "$instance" >> "$config/instances"
  fi
done
for launcher in "$engine"/launchers/*/; do
  [ -d "$launcher" ] || continue
  ln -sfn "${launcher%/}" "$skills/$(basename "$launcher")"
done
