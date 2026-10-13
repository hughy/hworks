#!/usr/bin/env bash
# Set up hworks on this machine. Safe to rerun.
# usage: install.sh [--profile <name>] [--check]
#   --profile <name>  apply a model profile with models.sh after linking
#   --check           report what is installed and what differs; change nothing
#
# Links global/AGENTS.md to the pi agent dir, ~/.claude/CLAUDE.md, and ~/.codex/AGENTS.md, links the agent
# roles and the autonomy and hughy-mode extensions into the pi agent dir, adds skills/ to pi settings, and creates the
# scratch root. A destination that is a real file is replaced only when its content is identical;
# otherwise install reports it and leaves it alone.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
pi=${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}
settings=${PI_SETTINGS:-$pi/settings.json}
tasks=${HWORKS_TASKS_DIR:-$HOME/.local/state/agent-tasks}

check=0; profile=
while [ $# -gt 0 ]; do
  case "$1" in
    --check) check=1; shift ;;
    --profile) profile=${2:?--profile needs a name}; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

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
link "$root/agents" "$pi/agents/hworks"
link "$root/extensions/autonomy.ts" "$pi/extensions/autonomy.ts"
link "$root/extensions/hughy-mode.ts" "$pi/extensions/hughy-mode.ts"

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

if [ -n "$profile" ] && [ "$check" = 0 ]; then "$root/scripts/models.sh" "$profile"; fi
if [ "$check" = 0 ] && [ "$status" = 0 ]; then echo "installed; run /reload in pi or start a new session"; fi
exit "$status"
