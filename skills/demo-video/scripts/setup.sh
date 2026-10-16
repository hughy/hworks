#!/usr/bin/env bash
# Sets up the demo-video toolchain in a cache dir: a Python venv with Kokoro TTS and Pillow, plus the Kokoro model files.
# --no-tts installs Pillow only and skips the models, enough for a silent video. Rerun without it to add TTS.
# Safe to rerun. Prints the venv python path on the last line.
set -euo pipefail
cache=${DEMO_VIDEO_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/demo-video}
python=${PYTHON:-python3}
tts=1
case "${1:-}" in
  "") ;;
  --no-tts) tts=0 ;;
  *) echo "usage: setup.sh [--no-tts]" >&2; exit 2 ;;
esac
release=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0

for tool in ffmpeg ffprobe node; do
  command -v "$tool" >/dev/null || { echo "setup: $tool not found; install it (macOS: brew install ffmpeg node)" >&2; exit 1; }
done
mkdir -p "$cache"
if [[ ! -x "$cache/venv/bin/python" ]]; then
  "$python" -m venv "$cache/venv"
fi
packages=(pillow)
if [[ $tts == 1 ]]; then packages+=(kokoro-onnx==0.6.1 soundfile); fi
"$cache/venv/bin/pip" install -q --disable-pip-version-check "${packages[@]}"
if [[ $tts == 1 ]]; then
  for f in kokoro-v1.0.onnx voices-v1.0.bin; do
    if [[ ! -s "$cache/$f" ]]; then
      echo "setup: downloading $f" >&2
      curl -fL --retry 3 -o "$cache/$f.part" "$release/$f"
      mv "$cache/$f.part" "$cache/$f"
    fi
  done
fi
echo "$cache/venv/bin/python"
