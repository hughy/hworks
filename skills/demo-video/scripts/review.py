"""Check a take without watching it: a per-line timing table and a contact sheet of stills taken during each line.

usage: review.py <dir> <video.mp4> [--offset 0.9] [--keys k1,k2] [--sheet stills/sheet-v1.png]
Timing columns: start in the video, speech length, slot until the next line starts, and dead air (slot - speech).
"""
import argparse, json, math, os, subprocess, tempfile
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("video")
    ap.add_argument("--offset", type=float, default=0.9, help="seconds into each line to grab the still; capped at half the line")
    ap.add_argument("--keys", help="comma-separated line keys for the sheet; default all")
    ap.add_argument("--sheet", default="stills/sheet.png")
    a = ap.parse_args()
    tl = json.load(open(os.path.join(a.dir, "timeline.json")))
    durations = json.load(open(os.path.join(a.dir, "audio/durations.json")))
    script = json.load(open(os.path.join(a.dir, "script.json")))
    voice = [c for c in tl["cues"] if c["kind"] == "voice"]
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.video], capture_output=True, text=True, check=True)
    length = float(out.stdout)
    # compose.py cuts the video to end exactly at timeline end, so the video's zero is end - length.
    t0 = tl["end"] - length

    speech = dead = 0.0
    print(f"{'start':>6} {'speech':>6} {'slot':>5} {'dead':>5}  key: text")
    for i, c in enumerate(voice):
        start = c["t"] - t0
        nxt = (voice[i + 1]["t"] - t0) if i + 1 < len(voice) else length
        d = durations[c["key"]]
        gap = max(0.0, (nxt - start) - d)
        speech += d
        dead += gap
        flag = "  <- dead air" if gap > 1.5 else ""
        print(f"{start:6.1f} {d:6.1f} {nxt - start:5.1f} {gap:5.1f}  {c['key']}: {script['lines'][c['key']][:70]}{flag}")
    print(f"video {length:.1f}s = speech {speech:.1f}s + dead {dead:.1f}s + lead-in {voice[0]['t'] - t0 if voice else 0:.1f}s")

    keys = set(a.keys.split(",")) if a.keys else None
    picks = [c for c in voice if not keys or c["key"] in keys]
    if not picks:
        return
    tmp = tempfile.mkdtemp()
    tiles = []
    for i, c in enumerate(picks):
        f = os.path.join(tmp, f"{i:03d}.png")
        at = min(c["t"] - t0 + min(a.offset, durations[c["key"]] / 2), length - 0.05)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", a.video, "-frames:v", "1", "-vf", "scale=720:-2", f], check=True)
        tiles.append(Image.open(f))
    cols = 3
    w, h = tiles[0].size
    sheet = Image.new("RGB", (w * cols, h * math.ceil(len(tiles) / cols)), "white")
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * w, (i // cols) * h))
    path = os.path.join(a.dir, a.sheet)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sheet.save(path)
    print(f"review: sheet of {len(tiles)} stills at {path}, in line order: {', '.join(c['key'] for c in picks)}")


if __name__ == "__main__":
    main()
