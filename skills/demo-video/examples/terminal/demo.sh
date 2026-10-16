#!/usr/bin/env bash
# A stand-in for the command under demo. It prints steps on stdout and writes one JSON event per step to fd 3.
# A step event comes a moment before the step's first output line, so the page switches its label first.
# Run by hand, fd 3 is not open and the events are dropped.
set -euo pipefail
if ! { true >&3; } 2>/dev/null; then exec 3>/dev/null; fi
pause=${PAUSE:-0.5}

step() {
  printf '{"event":"step","title":"%s","note":"%s"}\n' "$1" "$2" >&3
  sleep 0.1
  echo
  echo "> $1"
}

echo "release-demo   registry.example.test"
echo "package        demo-cli 1.4.2"
sleep "$pause"

step resolve "look up the release"
sleep "$pause"
echo "  version      1.4.2  (latest)"
echo "  commit       3f9a2c1"
sleep "$pause"

step build "compile the artifacts"
sleep "$pause"
echo "  target       linux-amd64"
echo "  target       darwin-arm64"
sleep "$pause"
echo "  artifacts    2  (4.2 MB)"
sleep "$pause"

step publish "upload and verify"
sleep "$pause"
echo "  upload       demo-cli-1.4.2.tar.gz"
sleep "$pause"
echo "  checksum     verified"
echo
echo "published in 3.4s"
printf '{"event":"done"}\n' >&3
