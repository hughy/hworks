"""Turn <dir>/timeline.json into an mp4: decode each frame's clock strip, retime frames by draw time, mix voice and sfx cues.

usage: compose.py <dir> <out.mp4> [--width 1920] [--fps 30]
"""
import argparse, json, os, subprocess, sys
from PIL import Image


def quote(p):
    # ffconcat quoting: close the quote, emit an escaped quote, reopen.
    return "'" + os.path.abspath(p).replace("'", "'\\''") + "'"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=30)
    a = ap.parse_args()
    a.dir = os.path.abspath(a.dir)
    tl = json.load(open(os.path.join(a.dir, "timeline.json")))
    clk, vw, vh, end = tl["clock"], tl["viewport"]["width"], tl["viewport"]["height"], tl["end"]

    def drawn_at(path):
        im = Image.open(path).convert("L")
        w, h = im.size
        k = w / vw
        px = [im.getpixel((int((i + 0.5) * clk["cellW"] * k), h - 1 - int(clk["height"] * k / 2))) for i in range(clk["cells"])]
        hi, lo = px[0], px[1]
        if hi - lo < 100:
            return None
        v = 0
        for p in px[2:]:
            v = v * 2 + (p < (hi + lo) / 2)
        return clk["base"] + v / 100

    frames, last, bad = [], -1.0, 0
    for fr in tl["frames"]:
        t = drawn_at(fr["file"])
        if t is None:
            bad += 1
            continue
        if t <= last or t > end:
            continue
        frames.append({"file": fr["file"], "t": t, "lag": fr["t"] - t})
        last = t
    if not frames:
        sys.exit("compose: no decodable frames; is the clock strip covered or cropped?")
    lags = [f["lag"] for f in frames]
    print(f"compose: frames kept {len(frames)}/{len(tl['frames'])}, undecodable {bad}, arrival lag {min(lags):.2f}..{max(lags):.2f}s")
    if frames[-1]["t"] < end - 1:
        print(f"compose: warning: last frame drawn {end - frames[-1]['t']:.1f}s before end; raise the recorder tail", file=sys.stderr)

    t0 = frames[0]["t"]
    concat = os.path.join(a.dir, "frames.txt")
    with open(concat, "w") as f:
        f.write("ffconcat version 1.0\n")
        for i, fr in enumerate(frames):
            nxt = frames[i + 1]["t"] if i + 1 < len(frames) else end
            f.write(f"file {quote(fr['file'])}\nduration {max(nxt - fr['t'], 0.001):.4f}\n")
        f.write(f"file {quote(frames[-1]['file'])}\n")

    total = end - t0
    cues = tl["cues"]
    inputs, filters = [], []
    for i, c in enumerate(cues):
        inputs += ["-i", c["file"]]
        ms = max(0, int((c["t"] - t0) * 1000))
        gain = c.get("gain", 1.0)
        filters.append(f"[{i + 1}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={gain},adelay={ms}|{ms}[a{i}]")
    if cues:
        mix = "".join(f"[a{i}]" for i in range(len(cues)))
        filters.append(f"{mix}amix=inputs={len(cues)}:normalize=0:dropout_transition=0,apad,atrim=0:{total:.3f},loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]")
    else:
        filters.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[aout]")
    height = round(a.width * (vh - clk["height"]) / vw / 2) * 2
    filters.append(f"[0:v]fps={a.fps},crop=iw:ih-ih*{clk['height']}/{vh}:0:0,scale={a.width}:{height}:flags=lanczos,format=yuv420p[vout]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", concat, *inputs,
           "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
           "-movflags", "+faststart", "-t", f"{total:.3f}", a.out]
    subprocess.run(cmd, check=True)
    print(f"compose: wrote {a.out} ({total:.1f}s)")


if __name__ == "__main__":
    main()
