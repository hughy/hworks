#!/usr/bin/env bash
# Checks scripts/shot.mjs against static pages served by python3 -m http.server: names, sizes, overflow, seeding, failures.
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
hang=
cleanup() { for p in $server $hang; do kill "$p" 2>/dev/null; done; true; }
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

# --action starts a page script that outlives the shots; --at times each shot from the action start.
mkdir -p "$site/timed"
cat >"$site/timed/index.html" <<'EOF'
<!doctype html><html><head><style>body{margin:0}</style></head><body><p>timed page</p><script>
  window.start = async () => {
    setTimeout(() => { const d = document.createElement("div"); d.style.cssText = "width:1600px;height:20px"; document.body.append(d); }, 700);
    await new Promise((r) => setTimeout(r, 60000));
  };
</script></body></html>
EOF
node "$shot" "$base" --path /timed/ --viewports 800x600 --settle 0 --action 'start()' --at 0.2,1.5 --out "$work/timed" >"$work/timed.jsonl"
python3 - "$work/timed" "$work/timed.jsonl" <<'PY'
import json, os, sys
out, log = sys.argv[1], sys.argv[2]
shots = [json.loads(l) for l in open(log)]
def check(cond, msg):
    if not cond:
        sys.exit(f"shot: {msg}\n{open(log).read()}")
check(sorted(os.listdir(out)) == ["timed-800x600-t0.2.png", "timed-800x600-t1.5.png"], f"timed files {sorted(os.listdir(out))}")
check([s["at"] for s in shots] == [0.2, 1.5], "want one JSON line per --at time, in order")
check([s["overflowX"] for s in shots] == [False, True], f"the page should overflow only after 0.7 s, got {[s['overflowX'] for s in shots]}")
check(all(s["file"] and os.path.exists(s["file"]) and "error" not in s for s in shots), "a timed shot failed")
PY
if node "$shot" "$base" --path /timed/ --at soon --out "$work/badat" >/dev/null 2>&1; then
  echo "shot: a bad --at exited 0" >&2; exit 1
fi

if node "$shot" "$base" --path /narrow/ --path /missing/ --viewports 800x600 --settle 0 --out "$work/fail" >"$work/fail.jsonl" 2>"$work/fail.err"; then
  echo "shot: a missing page exited 0" >&2; exit 1
fi
grep -q "FAILED $base/missing/ at 800x600: HTTP 404" "$work/fail.err" || { echo "shot: missing page not named:" >&2; cat "$work/fail.err" >&2; exit 1; }
grep -q '"path":"/narrow/".*"overflowX":false' "$work/fail.jsonl" || { echo "shot: good page not reported beside a failed one" >&2; exit 1; }
[[ -s "$work/fail/missing-800x600.png" ]] || { echo "shot: no PNG of the 404 page" >&2; exit 1; }

if node "$shot" "$base" --path /narrow/ --viewports 800x600 --wait-for '#never' --timeout 500 --out "$work/sel" >/dev/null 2>"$work/sel.err"; then
  echo "shot: a missing selector exited 0" >&2; exit 1
fi
grep -q "FAILED $base/narrow/ at 800x600: selector #never not visible" "$work/sel.err" || { echo "shot: missing selector not named:" >&2; cat "$work/sel.err" >&2; exit 1; }
[[ -s "$work/sel/narrow-800x600.png" ]] || { echo "shot: no PNG of the page that never showed the selector" >&2; exit 1; }

# A socket that accepts connections and never answers keeps a font load pending, so page.screenshot waits on fonts and times out.
python3 -u -c '
import socket, time
s = socket.socket()
s.bind(("127.0.0.1", 0))
s.listen(16)
print(s.getsockname()[1])
held = []
while True:
    held.append(s.accept()[0])
' >"$work/hang.port" 2>&1 &
hang=$!
hang_port=
for _ in $(seq 50); do
  hang_port=$(head -1 "$work/hang.port")
  [[ -n "$hang_port" ]] && break
  sleep 0.1
done
[[ "$hang_port" =~ ^[0-9]+$ ]] || { echo "shot: hang server did not start: $(cat "$work/hang.port")" >&2; exit 1; }
mkdir -p "$site/fonts"
cat >"$site/fonts/index.html" <<EOF
<!doctype html><html><body><p>font never loads</p><script>
  addEventListener("load", () => {
    const f = new FontFace("hang", "url(http://127.0.0.1:$hang_port/hang.woff2)");
    document.fonts.add(f);
    f.load().catch(() => {});
  });
</script></body></html>
EOF
if node "$shot" "$base" --path /fonts/ --path /narrow/ --viewports 800x600 --settle 0 --timeout 1500 --out "$work/cap" >"$work/cap.jsonl" 2>"$work/cap.err"; then
  echo "shot: a failed screenshot exited 0" >&2; exit 1
fi
grep -q "FAILED $base/fonts/ at 800x600: screenshot failed" "$work/cap.err" || { echo "shot: failed screenshot not named:" >&2; cat "$work/cap.err" >&2; exit 1; }
grep -q '"path":"/fonts/".*"file":null.*"error":"screenshot failed' "$work/cap.jsonl" || { echo "shot: failed screenshot has no JSON line:" >&2; cat "$work/cap.jsonl" >&2; exit 1; }
grep -q '"path":"/narrow/".*"overflowX":false' "$work/cap.jsonl" || { echo "shot: shot after a failed screenshot did not run:" >&2; cat "$work/cap.jsonl" "$work/cap.err" >&2; exit 1; }
[[ -f "$work/cap/narrow-800x600.png" ]] || { echo "shot: no PNG for the shot after a failed screenshot" >&2; exit 1; }

# An image from the hanging socket keeps the load event from firing, so page.goto times out after the text has rendered.
mkdir -p "$site/slow"
cat >"$site/slow/index.html" <<EOF
<!doctype html><html><head><style>body{margin:0}</style></head><body><p>slow page</p>
<img src="http://127.0.0.1:$hang_port/hang.png"></body></html>
EOF
if node "$shot" "$base" --path /slow/ --viewports 800x600 --settle 0 --timeout 1500 --out "$work/slow" >"$work/slow.jsonl" 2>"$work/slow.err"; then
  echo "shot: a timed-out load exited 0" >&2; exit 1
fi
grep -q "FAILED $base/slow/ at 800x600: load failed: .*Timeout" "$work/slow.err" || { echo "shot: timed-out load not named:" >&2; cat "$work/slow.err" >&2; exit 1; }
grep -q '"path":"/slow/","viewport":"800x600","file":"'"$work"'/slow/slow-800x600.png","scrollWidth":800,"innerWidth":800,.*"overflowX":false,.*"error":"load failed: [^;]*"}$' "$work/slow.jsonl" \
  || { echo "shot: timed-out load not captured best-effort:" >&2; cat "$work/slow.jsonl" >&2; exit 1; }
[[ -s "$work/slow/slow-800x600.png" ]] || { echo "shot: no PNG after a timed-out load" >&2; exit 1; }

# A refused connection leaves only Chrome's error page, so there is nothing worth capturing.
closed_port=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
if node "$shot" "http://127.0.0.1:$closed_port" --path /x/ --viewports 800x600 --settle 0 --out "$work/refused" >"$work/refused.jsonl" 2>"$work/refused.err"; then
  echo "shot: a refused connection exited 0" >&2; exit 1
fi
grep -q '"path":"/x/".*"file":null.*"error":"load failed: [^;]*ERR_CONNECTION_REFUSED' "$work/refused.jsonl" || { echo "shot: refused connection not reported:" >&2; cat "$work/refused.jsonl" >&2; exit 1; }
[[ -z "$(ls -A "$work/refused")" ]] || { echo "shot: refused connection wrote a file: $(ls "$work/refused")" >&2; exit 1; }

# A server that accepts the connection and never answers leaves the page at about:blank, so only the load error counts.
# A measure or capture attempt would append its own error after a ';'.
if node "$shot" "http://127.0.0.1:$hang_port" --path /x/ --viewports 800x600 --settle 0 --timeout 1500 --out "$work/silent" >"$work/silent.jsonl" 2>"$work/silent.err"; then
  echo "shot: a server that never answers exited 0" >&2; exit 1
fi
grep -q '"path":"/x/".*"file":null,"scrollWidth":null,.*"error":"load failed: [^;]*Timeout[^;]*"}$' "$work/silent.jsonl" \
  || { echo "shot: silent server not reported as a load error alone:" >&2; cat "$work/silent.jsonl" >&2; exit 1; }
[[ -z "$(ls -A "$work/silent")" ]] || { echo "shot: silent server wrote a file: $(ls "$work/silent")" >&2; exit 1; }

# A main thread that never yields blocks page.evaluate, which has no timeout of its own.
mkdir -p "$site/busy"
cat >"$site/busy/index.html" <<'EOF'
<!doctype html><html><body><p>busy page</p><script>
  addEventListener("load", () => setTimeout(() => { for (;;) {} }, 0));
</script></body></html>
EOF
if node "$shot" "$base" --path /busy/ --path /narrow/ --viewports 800x600 --settle 200 --timeout 1500 --out "$work/busy" >"$work/busy.jsonl" 2>"$work/busy.err"; then
  echo "shot: a busy page exited 0" >&2; exit 1
fi
grep -q "FAILED $base/busy/ at 800x600: measure failed: timed out after 1500 ms" "$work/busy.err" || { echo "shot: failed measure not named:" >&2; cat "$work/busy.err" >&2; exit 1; }
grep -q '"path":"/busy/".*"overflowX":null.*"error":"measure failed' "$work/busy.jsonl" || { echo "shot: failed measure has no JSON line:" >&2; cat "$work/busy.jsonl" >&2; exit 1; }
grep -q '"path":"/narrow/".*"overflowX":false' "$work/busy.jsonl" || { echo "shot: shot after a busy page did not run:" >&2; cat "$work/busy.jsonl" "$work/busy.err" >&2; exit 1; }

echo "shot: ok ($work)"
