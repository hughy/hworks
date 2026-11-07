#!/usr/bin/env bash
# Set up hworks on this machine. Safe to rerun.
# usage: install.sh [--profile <name>] [--amp] [--check]
#   --amp             also link Amp guidance and machine-local skills
#   --profile <name>  apply a model profile with models.sh after linking
#   --check           report what is installed and what differs; change nothing
#
# Links global/AGENTS.md to the pi agent dir, ~/.claude/CLAUDE.md, and ~/.codex/AGENTS.md, links the agent
# roles and every extensions/*.ts into the pi agent dir, adds skills/ to pi settings, and creates the
# scratch root. A destination that is a real file is replaced only when its content is identical;
# otherwise install reports it and leaves it alone.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
pi=${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}
settings=${PI_SETTINGS:-$pi/settings.json}
tasks=${HWORKS_TASKS_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/agent-tasks}

check=0; profile=; amp=0
while [ $# -gt 0 ]; do
  case "$1" in
    --check) check=1; shift ;;
    --amp) amp=1; shift ;;
    --profile) profile=${2:?--profile needs a name}; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

# A linked worktree is disposable; permanent user links must come from a standalone clone.
git_dir=$(unset $(git rev-parse --local-env-vars); git -C "$root" rev-parse --absolute-git-dir 2>/dev/null || true)
common=$(unset $(git rev-parse --local-env-vars); git -C "$root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
if [ "$check" = 0 ] && [ -n "$git_dir" ] && [ "$git_dir" != "$common" ]; then
  echo "refusing installation from a linked worktree: $root" >&2
  echo "Run install.sh from a durable standalone clone instead (git common dir: $common)." >&2
  exit 1
fi

status=0
say() { printf '%-8s %s\n' "$1" "$2"; }
resolved() { realpath "$1" 2>/dev/null || true; }

link() {
  local src=$1 dest=$2
  if [ -L "$dest" ] && [ "$(resolved "$dest")" = "$(resolved "$src")" ]; then say ok "$dest"; return; fi
  if [ -e "$dest" ] && [ ! -L "$dest" ] && ! { [ -f "$dest" ] && cmp -s "$src" "$dest"; }; then
    say differs "$dest is not a link to $src; compare them, move it aside, and rerun"
    status=1; return
  fi
  if [ "$check" = 1 ]; then say missing "$dest -> $src"; status=1; return; fi
  local was=""; [ -L "$dest" ] && was=" (was $(readlink "$dest"))"
  mkdir -p "$(dirname "$dest")"
  rm -f "$dest"
  ln -s "$src" "$dest"
  say linked "$dest -> $src$was"
}

if [ "$root" != "$HOME/dev/hworks" ] && [ "$(resolved "$HOME/dev/hworks")" != "$root" ]; then
  say warn "global/AGENTS.md refers to ~/dev/hworks; clone there or link ~/dev/hworks to $root"
fi

link "$root/global/AGENTS.md" "$pi/AGENTS.md"

# pi also loads AGENTS.md from every ancestor of the working directory, deduped by path, not by target,
# so a ~/AGENTS.md pointing here would load the same guidance twice in any directory under ~.
if [ -L "$HOME/AGENTS.md" ] && [ "$(resolved "$HOME/AGENTS.md")" = "$(resolved "$root/global/AGENTS.md")" ]; then
  if [ "$check" = 1 ]; then say extra "$HOME/AGENTS.md (pi would load the guidance twice under ~)"; status=1
  else rm "$HOME/AGENTS.md"; say removed "$HOME/AGENTS.md (link to global/AGENTS.md; pi reads $pi/AGENTS.md)"
  fi
elif [ -e "$HOME/AGENTS.md" ]; then
  say note "$HOME/AGENTS.md is not from hworks; pi loads it after $pi/AGENTS.md in directories under ~"
fi
link "$root/global/AGENTS.md" "$HOME/.claude/CLAUDE.md"
link "$root/global/AGENTS.md" "$HOME/.codex/AGENTS.md"
if [ "$amp" = 1 ]; then
  if [ -L "$HOME/.config/amp/AGENTS.md" ] && [ "$(resolved "$HOME/.config/amp/AGENTS.md")" != "$(resolved "$root/global/AGENTS.md")" ]; then
    say differs "$HOME/.config/amp/AGENTS.md is not a link to $root/global/AGENTS.md; compare them, move it aside, and rerun"
    status=1
  else
    link "$root/global/AGENTS.md" "$HOME/.config/amp/AGENTS.md"
  fi
  for skill in "$root"/skills/*; do
    [ -f "$skill/SKILL.md" ] || continue
    name=$(basename "$skill")
    # Amp loads only the first skill by name. Keep a fallback even if shared roots are disabled.
    link "$skill" "$HOME/.config/amp/skills/$name"
  done
fi
link "$root/agents" "$pi/agents/hworks"
for ext in "$root"/extensions/*.ts; do
  [ -e "$ext" ] || continue
  link "$ext" "$pi/extensions/$(basename "$ext")"
done

skills_path=$root/skills
tilde='~'
case "$skills_path" in "$HOME"/*) skills_path="$tilde/${skills_path#"$HOME"/}" ;; esac
result=$(node -e '
  const fs = require("fs"), os = require("os");
  const [file, want, check] = process.argv.slice(1);
  const expand = (p) => p.replace(/^~(?=\/)/, os.homedir());
  const d = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : {};
  const skills = Array.isArray(d.skills) ? d.skills : [];
  if (skills.some((s) => expand(s) === expand(want))) { console.log("ok"); process.exit(0); }
  if (check === "1") { console.log("missing"); process.exit(0); }
  if (fs.existsSync(file)) fs.copyFileSync(file, file + ".bak-install");
  fs.mkdirSync(require("path").dirname(file), { recursive: true });
  d.skills = [...skills, want];
  fs.writeFileSync(file, JSON.stringify(d, null, 2) + "\n");
  console.log("added");
' "$settings" "$skills_path" "$check")
case "$result" in
  ok) say ok "$settings skills includes $skills_path" ;;
  missing) say missing "$settings skills entry $skills_path"; status=1 ;;
  added) say added "$skills_path to $settings skills (backup: $settings.bak-install)" ;;
esac

if [ -d "$tasks" ]; then say ok "$tasks"
elif [ "$check" = 1 ]; then say missing "$tasks"; status=1
else mkdir -p "$tasks"; say created "$tasks"
fi

# Instance paths are supplied by the operator; never repoint the engine during hworks setup.
hoffice_config=${HOFFICE_CONFIG_DIR:-$HOME/.config/hoffice}
hoffice_home=$(cat "$hoffice_config/home" 2>/dev/null || true)
if [ -f "$root/hoffice/scripts/install.sh" ] && { [ -z "$hoffice_home" ] || [ "$(resolved "$hoffice_home")" != "$(resolved "$root/hoffice")" ]; }; then
  printf -v hoffice_install '%q/scripts/install.sh <instance...>' "$root/hoffice"
  say note "hoffice setup is separate; run: $hoffice_install"
fi

if [ -n "$profile" ] && [ "$check" = 0 ]; then "$root/scripts/models.sh" "$profile"; fi
if [ "$check" = 0 ] && [ "$status" = 0 ]; then echo "installed; run /reload in pi or start a new session"; fi
exit "$status"
