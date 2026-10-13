#!/usr/bin/env bash
# Apply a model profile: write each agent role's model to pi settings (subagents.agentOverrides.<role>.model)
# and record the profile so hughy-router can read its slots. Profiles come from models.conf and models.d/*.conf.
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
roles() { for f in "$agents"/*.md; do basename "$f" .md; done; }

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
    [ -f "$agents/$role.md" ] && continue
    [ "$model" = "-" ] && model="(session model)"
    printf '%-12s %s (slot)\n' "$role" "$model"
  done
}

cmd=${1:-}
case "$cmd" in
  ""|-h|--help) sed -n '2,5p' "$0"; exit 2 ;;
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
  [ -f "$agents/$role.md" ] && args+=("$role" "$model")
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
