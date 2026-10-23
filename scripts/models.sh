#!/usr/bin/env bash
# Apply a model profile: write each agent role's model to pi settings (subagents.agentOverrides.<role>.model)
# and record the profile so hughy-router can read its slots. Profiles come from models.conf and models.d/*.conf.
# A role is an agent role when agents/<role>.md exists or HWORKS_MODEL_AGENTS names it (comma- or space-separated;
# set in the environment or in adapters/local/*.env), for agents another package defines. Other roles are slots.
# usage: models.sh show
#        models.sh <profile>
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
agents="$root/agents"
marker="$root/.models-profile"
settings=${PI_SETTINGS:-$HOME/.pi/agent/settings.json}

rows() {
  local f
  for f in "$root/models.conf" "$root"/models.d/*.conf; do if [ -f "$f" ]; then cat "$f"; fi; done | awk '!/^#/ && NF'
}
active() { [ -f "$marker" ] && cat "$marker" || echo inherit; }
extra_agents() {
  if [ -n "${HWORKS_MODEL_AGENTS+x}" ]; then printf '%s\n' "$HWORKS_MODEL_AGENTS"; return; fi
  local f
  for f in "$root"/adapters/local/*.env; do if [ -f "$f" ]; then sed -n 's/^HWORKS_MODEL_AGENTS=//p' "$f"; fi; done | tail -n 1 | tr -d "\"'"
}
extras=$(extra_agents | tr ',' ' ')
is_agent() {
  [ -f "$agents/$1.md" ] && return 0
  case " $extras " in *" $1 "*) return 0 ;; esac
  return 1
}
roles() {
  { for f in "$agents"/*.md; do basename "$f" .md; done; for r in $extras; do echo "$r"; done; } | awk '!seen[$0]++'
}

override() {
  [ -f "$settings" ] || return 0
  node -e '
    const d = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8"));
    const m = d?.subagents?.agentOverrides?.[process.argv[2]]?.model;
    if (m) process.stdout.write(m);
  ' "$settings" "$1"
}

show() {
  local p; p=$(active)
  echo "profile: $p"
  for role in $(roles); do
    want=$(rows | awk -v p="$p" -v r="$role" '$1==p && $2==r {print $3}')
    got=$(override "$role")
    printf '%-12s %s' "$role" "${got:-(session model)}"
    if [ -n "$want" ] && [ "$want" != "-" ] && [ "$want" != "$got" ]; then printf '  (profile says %s; rerun models.sh %s)' "$want" "$p"; fi
    if [ "$want" = "-" ] && [ -n "$got" ]; then printf '  (profile says session model; rerun models.sh %s)' "$p"; fi
    echo
  done
  rows | awk -v p="$p" '$1==p {print $2, $3}' | while read -r role model; do
    is_agent "$role" && continue
    [ "$model" = "-" ] && model="(session model)"
    printf '%-12s %s (slot)\n' "$role" "$model"
  done
}

cmd=${1:-}
case "$cmd" in
  ""|-h|--help) sed -n '2,7p' "$0"; exit 2 ;;
  show) show; exit 0 ;;
esac

profile=$cmd
pins=$(rows | awk -v p="$profile" '$1==p {print $2, $3}')
[ -n "$pins" ] || { echo "no profile named $profile" >&2; echo "profiles: $(rows | awk '{print $1}' | sort -u | tr '\n' ' ')" >&2; exit 1; }

mkdir -p "$(dirname "$settings")"
[ -f "$settings" ] || echo '{}' > "$settings"
cp "$settings" "$settings.bak-models"

args=()
while read -r role model; do
  is_agent "$role" && args+=("$role" "$model")
done <<< "$pins"

node -e '
  const fs = require("fs");
  const [file, ...pairs] = process.argv.slice(1);
  const d = JSON.parse(fs.readFileSync(file, "utf8"));
  d.subagents ??= {};
  d.subagents.agentOverrides ??= {};
  const o = d.subagents.agentOverrides;
  for (let i = 0; i < pairs.length; i += 2) {
    const [role, model] = [pairs[i], pairs[i + 1]];
    if (model === "-") {
      if (o[role]) { delete o[role].model; if (!Object.keys(o[role]).length) delete o[role]; }
    } else {
      o[role] = { ...(o[role] || {}), model };
    }
  }
  fs.writeFileSync(file, JSON.stringify(d, null, 2) + "\n");
' "$settings" "${args[@]}"
echo "$profile" > "$marker"

echo "profile $profile applied to $settings (backup: $settings.bak-models):"
show
echo "Run /reload in pi."
