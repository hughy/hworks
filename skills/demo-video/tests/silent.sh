#!/usr/bin/env bash
# End-to-end check of a narration-free video: no script.json or audio, a terminal page fed by a live run and then by its
# recording, a silent compose, and time-based review. Needs no TTS and no model files.
# usage: PLAYWRIGHT_FROM=<project with playwright>/package.json tests/silent.sh [python-with-pillow]
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
term=$here/examples/terminal
py=${1:-${DEMO_VIDEO_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/demo-video}/venv/bin/python}
[[ -x "$py" ]] || py=python3
work=$(mktemp -d)
servers=
trap 'for p in $servers; do kill "$p" 2>/dev/null; done; true' EXIT
fail() { echo "silent: $*" >&2; exit 1; }

# Starts server.mjs in the background and sets $url to its address.
serve() {
  local log=$work/server-$RANDOM.log
  node "$term/server.mjs" --port 0 "$@" >"$log" 2>&1 &
  servers="$servers $!"
  for _ in $(seq 50); do
    url=$(sed -n 's/^demo server on //p' "$log" | head -1)
    [[ -n "$url" ]] && return
    sleep 0.1
  done
  fail "server did not start: $(cat "$log")"
}

# A live run streams the command's lines and events and records them; a second live run is refused.
PAUSE=0.05 serve --runs "$work/live" -- "$term/demo.sh"
curl -sf -N --max-time 30 "$url/run" >"$work/live.sse" || fail "live run failed"
rec=$(ls "$work"/live/run-*.jsonl)
"$py" - "$rec" "$work/live.sse" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
kinds = [r["kind"] for r in rows]
assert kinds[0] == "cmd" and kinds[-1] == "exit" and rows[-1]["data"] == {"code": 0}, kinds
assert [r["data"]["title"] for r in rows if r["kind"] == "ev" and r["data"]["event"] == "step"] == ["resolve", "build", "publish"]
assert any(r["data"] == "published in 3.4s" for r in rows if r["kind"] == "out")
assert [r["t"] for r in rows] == sorted(r["t"] for r in rows)
assert "event: exit" in open(sys.argv[2]).read()
PY
curl -sf -N --max-time 10 "$url/run" | grep -q "already ran the command once" || fail "a second live run was not refused"

# Replay: the recording plays back with its original timing and starts no process.
mkdir -p "$work/runs"
cp "$term/sample-run.jsonl" "$work/runs/"
serve --runs "$work/runs"
mkdir "$work/take"
[[ ! -e "$work/take/script.json" ]] || fail "work dir should have no script.json"
DEMO_VIDEO_SKILL=$here node "$term/scenes.cjs" "$work/take" "$url/?replay=sample-run.jsonl&hold=1000" | tee "$work/record.log"
grep -q "no cues" "$work/record.log" || fail "the recorder logged cues"
"$py" "$here/scripts/compose.py" "$work/take" "$work/out.mp4" --width 960 | tee "$work/compose.log"
grep -q "undecodable 0," "$work/compose.log" || fail "frames failed to decode"
streams=$(ffprobe -v error -show_entries stream=codec_type -of csv=p=0 "$work/out.mp4" | sort | tr '\n' ' ')
[[ "$streams" == "audio video " ]] || fail "expected a silent audio track and a video stream, got $streams"

# Review without voice cues: a sheet from time stamps, a table-free report, an animation strip, and a cropped strip.
"$py" "$here/scripts/review.py" "$work/take" "$work/out.mp4" | tee "$work/review.log"
grep -q "no voice cues" "$work/review.log" || fail "review did not report the missing voice cues"
grep -q "dead air" "$work/review.log" && fail "review printed a voice table"
[[ -s "$work/take/stills/sheet.png" ]] || fail "no time-based contact sheet"
"$py" "$here/scripts/review.py" "$work/take" "$work/out.mp4" --every 3 --sheet stills/every.png | grep -q "sheet of [0-9]* stills at .*every.png, in order: 0.00s, 3.00s" || fail "--every sheet names wrong"
"$py" "$here/scripts/review.py" "$work/take" "$work/out.mp4" --range 2:3 --fps 4 --crop 0,0,480,120 --sheet stills/range.png | grep -q "sheet of 4 stills at .*range.png, in order: 2.00s, 2.25s, 2.50s, 2.75s" || fail "--range sheet names wrong"
"$py" - "$work/take/stills" <<'PY'
import sys
from PIL import Image
d = sys.argv[1]
assert Image.open(f"{d}/sheet.png").width == 6 * 480
w, h = Image.open(f"{d}/range.png").size
assert (w, h) == (4 * 480, 120), (w, h)
PY
if "$py" "$here/scripts/review.py" "$work/take" "$work/out.mp4" --every 2 --range 1:2 >/dev/null 2>&1; then fail "--every with --range exited 0"; fi

# The fake cursor stays hidden until the first move, with or without narration files.
mkdir "$work/cursor"
node - "$here" "file://$here/examples/app.html" "$work/cursor" <<'JS'
const [skill, url, dir] = process.argv.slice(2);
const { record } = require(`${skill}/scripts/recorder.cjs`);
const opacity = (s) => s.page.evaluate(() => getComputedStyle(document.querySelector(".ann-cursor")).opacity);
record({ dir, url, tail: 1, scale: 1, viewport: { width: 1280, height: 800 } }, async (s) => {
  if ((await opacity(s)) !== "0") throw new Error("cursor visible before any move");
  await s.click('[data-testid="run-small"]');
  await s.sleep(0.8);
  if ((await opacity(s)) !== "1") throw new Error("cursor hidden after a move");
}).catch((e) => { console.error(e.message); process.exit(1); });
JS
echo "silent: ok ($work)"
