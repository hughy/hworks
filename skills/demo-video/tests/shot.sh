#!/usr/bin/env bash
# Checks scripts/shot.mjs against two static pages served by python3 -m http.server: names, sizes, overflow, seeding, failures.
# usage: PLAYWRIGHT_FROM=<project with playwright>/package.json tests/shot.sh
# Exits 0 with a skip message when Playwright or its browser is not available.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
shot=$here/scripts/shot.mjs

if ! reason=$(node -e '
  const { loadChromium } = require(process.argv[1]);
  const channel = process.env.PLAYWRIGHT_CHANNEL || "chrome";
  (async () => {
    const browser = await loadChromium(process.env.PLAYWRIGHT_FROM).launch(channel === "bundled" ? {} : { channel });
    await browser.close();
  })().catch((e) => { console.log(e.message.split("\n")[0]); process.exit(1); });
' "$here/scripts/recorder.cjs" 2>&1); then
  echo "shot: skip, Playwright or its browser is unavailable ($reason)"
  exit 0
fi

work=$(mktemp -d)
server=
cleanup() { [[ -n "$server" ]] && kill "$server" 2>/dev/null; true; }
trap cleanup EXIT

site=$work/site
mkdir -p "$site/narrow" "$site/wide"
seed='<script>
  addEventListener("load", () => setTimeout(() => {
    if (localStorage.getItem("seed") !== "{\"ok\":true}") return;
    const d = document.createElement("div");
    d.id = "ready";
    d.textContent = "seeded";
    document.body.append(d);
  }, 150));
</script>'
cat >"$site/narrow/index.html" <<EOF
<!doctype html><html><head><style>body{margin:0}</style></head><body><p>narrow page</p>$seed</body></html>
EOF
cat >"$site/wide/index.html" <<EOF
<!doctype html><html><head><style>body{margin:0}</style></head><body>
<div style="width:1600px;height:40px;background:#c33">wide page</div>
<script>console.error("wide-boom")</script>$seed</body></html>
EOF

# Port 0 lets the OS pick a free port; the server prints the one it bound.
python3 -u -m http.server 0 --bind 127.0.0.1 --directory "$site" >"$work/server.log" 2>&1 &
server=$!
port=
for _ in $(seq 50); do
  port=$(sed -n 's/.*port \([0-9][0-9]*\).*/\1/p' "$work/server.log" | head -1)
  [[ -n "$port" ]] && break
  sleep 0.1
done
[[ -n "$port" ]] || { echo "shot: http.server did not start: $(cat "$work/server.log")" >&2; exit 1; }
base=http://127.0.0.1:$port

node "$shot" "$base" --path /narrow/ --path /wide/ --viewports 1280x800,1920x1080 \
  --wait-for '#ready' --settle 50 --local-storage 'seed={"ok":true}' --out "$work/out" --name t- >"$work/shots.jsonl"

python3 - "$work/out" "$work/shots.jsonl" <<'PY'
import json, os, struct, sys
out, log = sys.argv[1], sys.argv[2]
shots = [json.loads(l) for l in open(log)]
def check(cond, msg):
    if not cond:
        sys.exit(f"shot: {msg}\n{open(log).read()}")
expected = {f"t-{s}-{v}.png" for s in ("narrow", "wide") for v in ("1280x800", "1920x1080")}
check(sorted(os.listdir(out)) == sorted(expected), f"files {sorted(os.listdir(out))}, want {sorted(expected)}")
check(len(shots) == 4, f"want 4 JSON lines, got {len(shots)}")
for s in shots:
    check(os.path.basename(s["file"]) in expected and os.path.dirname(s["file"]) == out, f"unexpected file {s['file']}")
    with open(s["file"], "rb") as f:
        head = f.read(24)
    check(head[:8] == b"\x89PNG\r\n\x1a\n", f"{s['file']} is not a PNG")
    w, h = struct.unpack(">II", head[16:24])
    check(f"{w}x{h}" == s["viewport"], f"{s['file']} is {w}x{h}, want {s['viewport']}")
    check(s["innerWidth"] == w and s["innerHeight"] == h, f"inner size {s['innerWidth']}x{s['innerHeight']} for {s['viewport']}")
    wide_small = s["path"] == "/wide/" and s["viewport"] == "1280x800"
    check(s["overflowX"] is wide_small, f"overflowX {s['overflowX']} for {s['path']} at {s['viewport']}")
    check(s["overflowX"] == (s["scrollWidth"] > s["innerWidth"]), f"overflowX disagrees with widths for {s['path']}")
    check(s["overflowY"] is False, f"overflowY {s['overflowY']} for {s['path']} at {s['viewport']}")
    check(("wide-boom" in s["consoleErrors"]) == (s["path"] == "/wide/"), f"consoleErrors {s['consoleErrors']} for {s['path']}")
    check("error" not in s, f"unexpected error {s.get('error')}")
PY

if node "$shot" "$base" --path /narrow/ --path /missing/ --viewports 800x600 --settle 0 --out "$work/fail" >"$work/fail.jsonl" 2>"$work/fail.err"; then
  echo "shot: a missing page exited 0" >&2; exit 1
fi
grep -q "FAILED $base/missing/ at 800x600: HTTP 404" "$work/fail.err" || { echo "shot: missing page not named:" >&2; cat "$work/fail.err" >&2; exit 1; }
grep -q '"path":"/narrow/".*"overflowX":false' "$work/fail.jsonl" || { echo "shot: good page not reported beside a failed one" >&2; exit 1; }

if node "$shot" "$base" --path /narrow/ --viewports 800x600 --wait-for '#never' --timeout 500 --out "$work/sel" >/dev/null 2>"$work/sel.err"; then
  echo "shot: a missing selector exited 0" >&2; exit 1
fi
grep -q "FAILED $base/narrow/ at 800x600: selector #never not visible" "$work/sel.err" || { echo "shot: missing selector not named:" >&2; cat "$work/sel.err" >&2; exit 1; }

echo "shot: ok ($work)"
