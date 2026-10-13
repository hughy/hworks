"""Render every line in <dir>/script.json to <dir>/audio/<key>.wav with Kokoro, and write audio/durations.json.

usage: tts.py <dir> [--only key1,key2] [--phonemes]
  --only      rerender these keys and keep the other durations
  --phonemes  print how Kokoro will pronounce every distinct word after the speak map, then every line with digits
              or symbols in full (numbers and currency read in context), then exit
"""
import argparse, json, os, re, sys

CACHE = os.environ.get("DEMO_VIDEO_CACHE") or os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "demo-video")


def voice_for(voices, key):
    hit = next(((n, v) for n, v in voices.items() if v.get("prefix") and key.startswith(v["prefix"])), None)
    hit = hit or next(((n, v) for n, v in voices.items() if not v.get("prefix")), None)
    if not hit:
        sys.exit(f"tts: no voice for line {key}")
    return hit[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--only")
    ap.add_argument("--phonemes", action="store_true")
    a = ap.parse_args()
    a.dir = os.path.abspath(a.dir)
    script = json.load(open(os.path.join(a.dir, "script.json")))
    speak = script.get("speak", {})
    order = sorted(speak, key=len, reverse=True)

    # The map applies to the audio only; captions keep the written form.
    def spoken(text):
        for w in order:
            text = re.sub(rf"(?<!\w){re.escape(w)}(?!\w)", speak[w], text)
        return text

    keys = a.only.split(",") if a.only else list(script["lines"])
    unknown = [key for key in keys if key not in script["lines"]]
    if unknown:
        sys.exit(f"tts: no such lines: {', '.join(unknown)}")

    from kokoro_onnx import Kokoro

    k = Kokoro(os.path.join(CACHE, "kokoro-v1.0.onnx"), os.path.join(CACHE, "voices-v1.0.bin"))

    if a.phonemes:
        # Every word, not a heuristic subset: the phonemizer also gets ordinary dictionary words wrong.
        mapped = re.compile("|".join(rf"(?<!\w){re.escape(w)}(?!\w)" for w in order)) if order else None
        seen = set()
        for key, text in script["lines"].items():
            lang = voice_for(script["voices"], key).get("lang", "en-us")
            words = (mapped.findall(text) if mapped else []) + re.findall(r"(?<!['\w])[A-Za-z][A-Za-z'-]*", mapped.sub(" ", text) if mapped else text)
            for w in words:
                if (w, lang) in seen:
                    continue
                seen.add((w, lang))
                print(f"{w:18} -> {spoken(w):18} {k.tokenizer.phonemize(spoken(w), lang)}  [{lang}]")
        for key, text in script["lines"].items():
            if re.search(r"[0-9$%&@#+=/]", text):
                lang = voice_for(script["voices"], key).get("lang", "en-us")
                print(f"\n{key}: {spoken(text)}\n  {k.tokenizer.phonemize(spoken(text), lang)}")
        return

    import soundfile as sf

    out = os.path.join(a.dir, "audio")
    os.makedirs(out, exist_ok=True)
    dpath = os.path.join(out, "durations.json")
    durations = json.load(open(dpath)) if a.only and os.path.exists(dpath) else {}
    for key in keys:
        v = voice_for(script["voices"], key)
        samples, sr = k.create(spoken(script["lines"][key]), voice=v["voice"], speed=v.get("speed", 1.0), lang=v.get("lang", "en-us"))
        sf.write(os.path.join(out, f"{key}.wav"), samples, sr)
        durations[key] = round(len(samples) / sr, 3)
    durations = {key: durations[key] for key in script["lines"] if key in durations}
    json.dump(durations, open(dpath, "w"), indent=1)
    print(f"tts: {len(keys)} lines rendered, speech total {sum(durations.values()):.1f}s")


if __name__ == "__main__":
    main()
