#!/usr/bin/env bash
# End-to-end check of recorder, overlay, compose, and review on examples/app.html, with tones in place of TTS.
# usage: PLAYWRIGHT_FROM=<project with playwright>/package.json tests/smoke.sh [python-with-pillow]
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
py=${1:-${DEMO_VIDEO_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/demo-video}/venv/bin/python}
[[ -x "$py" ]] || py=python3
work=$(mktemp -d)
cp "$here/examples/script.json" "$work/"
mkdir -p "$work/audio"
"$py" - "$work" <<'PY'
import json, subprocess, sys
d = sys.argv[1]
lines = json.load(open(f"{d}/script.json"))["lines"]
durs = {}
for i, key in enumerate(lines):
    durs[key] = 1.2 + 0.3 * i
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={300 + 80 * i}:duration={durs[key]}", f"{d}/audio/{key}.wav"], check=True)
json.dump(durs, open(f"{d}/audio/durations.json", "w"))
PY
DEMO_VIDEO_SKILL=$here node "$here/examples/scenes.cjs" "$work" "file://$here/examples/app.html"
"$py" "$here/scripts/compose.py" "$work" "$work/out.mp4" --width 1280 | tee "$work/compose.log"
"$py" "$here/scripts/review.py" "$work" "$work/out.mp4" | tee "$work/review.log"
grep -q "undecodable 0," "$work/compose.log" || { echo "smoke: frames failed to decode" >&2; exit 1; }
n=$(grep -c "^ *[0-9.]* *[0-9.]* *[0-9.]* *[0-9.]*  [a-z-]*:" "$work/review.log")
[[ "$n" -eq 5 ]] || { echo "smoke: expected 5 voice cues, saw $n" >&2; exit 1; }
streams=$(ffprobe -v error -show_entries stream=codec_type -of csv=p=0 "$work/out.mp4" | sort | tr '\n' ' ')
[[ "$streams" == "audio video " ]] || { echo "smoke: expected audio and video streams, got $streams" >&2; exit 1; }
[[ -s "$work/stills/sheet.png" ]] || { echo "smoke: no contact sheet" >&2; exit 1; }
echo "smoke: ok ($work)"
