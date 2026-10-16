"""Check a take without watching it: a per-line timing table and a contact sheet of stills.

usage: review.py <dir> <video.mp4> [--offset 0.9] [--keys k1,k2] [--sheet stills/sheet-v1.png]
                 [--every <s> | --range <a>:<b> [--fps 6]] [--crop x,y,w,h] [--width <px>]
Timing columns: start in the video, speech length, slot until the next line starts, and dead air (slot - speech).
Sheet: by default one still during each voice line. --every <s> takes a still every s seconds of the video; with no voice
cues that is the default (every 2 s). --range <a>:<b> takes stills of that stretch at --fps, to check an animation frame by frame.
--crop cuts each still to a region (video pixels) before scaling.
"""
import argparse, json, math, os, subprocess, tempfile
from PIL import Image, ImageDraw


def load(path, none):
    return json.load(open(path)) if os.path.exists(path) else none


def still(video, at, out, width, crop):
    vf = (f"crop={crop}," if crop else "") + f"scale={width}:-2"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.3f}", "-i", video, "-frames:v", "1", "-vf", vf, out], check=True)


def label(im, text):
    d = ImageDraw.Draw(im)
    box = d.textbbox((0, 0), text)
    d.rectangle((0, 0, box[2] + 8, box[3] + 8), fill="black")
    d.text((4, 4), text, fill="white")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("video")
    ap.add_argument("--offset", type=float, default=0.9, help="seconds into each line to grab the still; capped at half the line")
    ap.add_argument("--keys", help="comma-separated line keys for the sheet; default all")
    ap.add_argument("--sheet", default="stills/sheet.png")
    ap.add_argument("--every", type=float, help="seconds between stills, instead of one per voice line")
    ap.add_argument("--range", help="a:b, seconds of the video; stills at --fps over that stretch")
    ap.add_argument("--fps", type=float, default=6, help="stills per second for --range")
    ap.add_argument("--crop", help="x,y,w,h in video pixels, applied before scaling")
    ap.add_argument("--width", type=int, help="tile width in pixels; default 720 for voice stills, 480 otherwise")
    a = ap.parse_args()
    if a.every is not None and a.range:
        ap.error("--every and --range are alternatives")
    if a.every is not None and a.every <= 0:
        ap.error("--every must be positive")
    crop = None
    if a.crop:
        try:
            x, y, w, h = (int(v) for v in a.crop.split(","))
        except ValueError:
            ap.error("--crop wants x,y,w,h as whole pixels")
        crop = f"{w}:{h}:{x}:{y}"
    tl = json.load(open(os.path.join(a.dir, "timeline.json")))
    durations = load(os.path.join(a.dir, "audio/durations.json"), {})
    script = load(os.path.join(a.dir, "script.json"), {"lines": {}})
    voice = [c for c in tl["cues"] if c["kind"] == "voice"]
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.video], capture_output=True, text=True, check=True)
    length = float(out.stdout)
    # compose.py cuts the video to end exactly at timeline end, so the video's zero is end - length.
    t0 = tl["end"] - length

    speech = dead = 0.0
    if voice:
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
    if voice:
        print(f"video {length:.1f}s = speech {speech:.1f}s + dead {dead:.1f}s + lead-in {voice[0]['t'] - t0:.1f}s")
    else:
        print(f"video {length:.1f}s, no voice cues")

    if a.range:
        try:
            lo, hi = (float(v) for v in a.range.split(":"))
        except ValueError:
            ap.error("--range wants a:b in seconds")
        if not 0 <= lo < hi or a.fps <= 0:
            ap.error("--range wants 0 <= a < b, and --fps positive")
        n = int((hi - lo) * a.fps + 1e-9)
        times, cols = [lo + i / a.fps for i in range(n)], 4
    elif a.every is not None or not voice:
        every = a.every if a.every is not None else 2.0
        if a.every is None:
            print(f"review: no voice cues; a still every {every:g} s (see --every, --range)")
        times, cols = [i * every for i in range(int(length / every) + 1)], 6
    else:
        times, cols = None, 3
    width = a.width or (720 if times is None else 480)
    tmp = tempfile.mkdtemp()
    tiles = []
    if times is None:
        keys = set(a.keys.split(",")) if a.keys else None
        picks = [c for c in voice if not keys or c["key"] in keys]
        names = [c["key"] for c in picks]
        stamps = [min(c["t"] - t0 + min(a.offset, durations[c["key"]] / 2), length - 0.05) for c in picks]
    else:
        stamps = [min(t, length - 0.05) for t in times]
        names = [f"{t:.2f}s" for t in stamps]
    for i, at in enumerate(stamps):
        f = os.path.join(tmp, f"{i:03d}.png")
        still(a.video, at, f, width, crop)
        im = Image.open(f).convert("RGB")
        if times is not None:
            label(im, f"{at:.2f}s")
        tiles.append(im)
    if not tiles:
        return
    w, h = tiles[0].size
    sheet = Image.new("RGB", (w * cols, h * math.ceil(len(tiles) / cols)), "white")
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * w, (i // cols) * h))
    path = os.path.join(a.dir, a.sheet)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sheet.save(path)
    print(f"review: sheet of {len(tiles)} stills at {path}, in order: {', '.join(names)}")


if __name__ == "__main__":
    main()
