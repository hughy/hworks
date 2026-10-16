# demo-video: recording a video

Paths are relative to the skill directory (`..` from this file); pass them as absolute paths.

The pipeline drives a real Chrome page with Playwright, injects an annotation layer, logs a cue for each spoken line, and captures frames over the Chrome DevTools screencast. ffmpeg then mixes the pre-rendered speech at the logged times.

- `scripts/setup.sh` makes a venv with Kokoro TTS and Pillow in `~/.cache/demo-video` (override with `DEMO_VIDEO_CACHE`), downloads the model and voices (about 350 MB), checks for `ffmpeg` and `node`, and prints the venv python. It is safe to rerun. `--no-tts` installs Pillow only and skips the download, which is all a silent video needs.
- `scripts/tts.py <dir>` renders `script.json` lines to `audio/*.wav` and `audio/durations.json`.
- `scripts/recorder.cjs` exports `record(opts, scenes)`. `examples/scenes.cjs` is a complete scene script to copy.
- `scripts/overlay.js` is the annotation layer the recorder injects.
- `scripts/compose.py <dir> <out.mp4>` builds the video.
- `scripts/review.py <dir> <video>` prints a per-line timing table and writes a contact sheet of stills.
- `examples/terminal/` is a kit for a silent video of a live command (see Live command-line demos).
- `tests/smoke.sh` runs the whole chain on `examples/app.html` with tones in place of speech. `tests/silent.sh` runs the silent chain on the terminal kit's recorded stream, with no narration files.

## Workflow

1. Run `scripts/setup.sh` (`--no-tts` for a silent video). Run `tts.py`, `compose.py`, and `review.py` with the python it prints.
2. Make a work dir in scratch, never in the target repo. Everything below writes there.
3. Rehearse before scripting. Drive every scenario once through the app's API, CLI, or a headless page, and note each outcome, how long it takes, and the numbers it shows. Write narration only from observed results. A line that predicts the wrong outcome costs a whole take.
4. Make takes repeatable. List every store the app reads or writes: databases, chain or emulator state, files on disk, server memory, logs it renders. Back them up before the first take. Then write `restore.sh` in the work dir: it puts each store back, resets the app, and checks the app is healthy. A database or chain snapshot does not revert files the app wrote beside it. Run it after every take, failed ones included, and leave the user's environment as you found it. When the app computes deadlines or expiries from a store's clock, advance that clock right before each take; otherwise the first action after an idle stretch fails as expired.
5. Narrated video: write `script.json` (format below), run `tts.py --phonemes`, and fix every word that comes out wrong through the `speak` map. It lists every distinct word, then every line with digits or symbols in full. Read all of it: the phonemizer gets some dictionary words wrong (it reads "nonce" as "non-see"), and reads "$1,000 limit" as "dollar one thousand limit". Spell amounts out in words. Run `tts.py`. Speech dominates length: plan for the video to run 10 to 35 percent longer than the `speech total` it prints, more with slow app actions, and check with `review.py`. Cut words to hit a target length. A silent video skips this step (see Silent video).
6. Copy `examples/scenes.cjs` into the work dir and write the scenes (helpers below); for a live command, copy `examples/terminal/` instead (see Live command-line demos). Run it with `DEMO_VIDEO_SKILL` set to this skill's directory.
7. Take: run `restore.sh`, then `node scenes.cjs <dir> <url>`, then `restore.sh` again, then `compose.py`.
8. Review without watching (see below). Fix and retake until the review is clean.
9. Keep every delivered cut: copy the video, `script.json`, and the scene script to `backup/` with a version suffix before changing them, so any earlier version can be restored on request.

## script.json

```json
{
  "voices": {
    "narrator": { "voice": "af_heart", "speed": 1.0, "lang": "en-us" },
    "rival": { "voice": "bm_george", "speed": 0.95, "lang": "en-gb", "prefix": "v-", "label": "RIVAL", "alt": true }
  },
  "speak": { "USD": "U S D", "calldata": "call data" },
  "lines": { "intro": "...", "v-large": "...", "large-b": "..." }
}
```

- A line uses the first voice whose `prefix` starts its key, else the voice without a prefix. `label` prints above that voice's captions; `alt` gives them the alternate caption color.
- `speak` rewrites whole words in the audio only. Captions keep the written form.
- Kokoro voices that worked: `af_heart` for a narrator and `bm_george` for a contrasting second voice. `bm_lewis` and `am_onyx` are untested alternatives. Operating-system voices (`say`) sound robotic, and premium system voices may be blocked on managed machines.
- With two voices, let the second voice state each move and the narrator deliver the verdict. A narrator line that restates the move doubles the length.
- Keep the second voice in the tone the user asked for. A comedic voice undercuts a serious demo, and the reverse.
- Each line must be true at the moment it plays: who owns what, who loses what, and what the screen shows. Speak round numbers ("over forty thousand dollars"), and read exact numbers from the page at record time for bubbles.

## Scene helpers

`record({ dir, url, viewport, scale, channel, ready, theme, tail, quality }, async (s) => { ... })` gives each scene script:

- `s.say(key)`: shows the caption, logs the voice cue, and resolves when the line ends.
- `s.lead(key, action, at = 0.4)`: speaks the line and starts `action` at 40 percent of it, so the app's latency overlaps speech. Resolves when both finish. Use it for every line that leads into a click.
- `s.click(sel, { travel })`: moves the fake cursor over `travel` seconds (default 0.7), shows a ripple, and clicks for real. The screencast never captures the system cursor, so the overlay draws one.
- `s.ann.<fn>(...)`: `caption`, `card(kicker, title, emoji)`, `ring(sel, tone)`, `bubble(sel, html, { x, y, tone })`, `stamp(sel, text, tone, { dx, dy })`, `burst(sel, emojis)`, `clear()` (keeps caption and card), `clearAll()`. Tones are `good`, `bad`, `accent`, or none (ink for bubbles, accent for rings); stamps default to `good`. `theme` overrides the CSS variables `accent`, `good`, `bad`, `alt`, and `ink`.
- `s.rect(sel)`: the element's viewport rect. Place bubbles in free space computed from rects, and stamps in a gap between a row's label and its status, never over text.
- `s.sfx(file, gain)`: logs a sound effect, such as one of the system sounds.
- `s.page`, `s.lines`, `s.durations`, `s.sleep`.

Wait on app state (a `data-` attribute, a selector, text) after each action, never a fixed sleep. Set `ready` to wait for the selectors the scenes use. The recorder keeps capturing for `tail` seconds (default 25) after the scenes end. Frames are JPEGs at the viewport size times `scale` (default 2). A two-minute take at the defaults writes 1 GB or more to `frames/` (about 6 MB per second on a simple page, more on a busy one), which the next take replaces; lower `quality` (default 88) or `scale` to save space. The recorder bypasses the page's Content Security Policy so the overlay's inline styles apply. The overlay loads with every page, so a full navigation clears annotations; wait for the new page, then redraw them. Annotations are fixed to the viewport and placed from rects measured at call time, so keep the demo inside one viewport, or scroll first and annotate after.

## Why the clock strip

Screencast frames can arrive seconds after Chrome draws them, and the lag varies within one take; 16 seconds has been observed. The overlay draws a strip at the bottom of every frame, a white and a black sentinel cell plus 24 bits of draw time in centiseconds. `compose.py` decodes each frame's draw time, drops late duplicates, times the video by draw time, and crops the strip off. Keep page content you need out of the bottom 6 CSS px, and do not cover the bottom-left corner.

## Silent video

Without `<dir>/script.json` and `<dir>/audio/` the recorder runs with no lines, and `compose.py` writes a silent audio track. Drive the page with `s.page`, `s.ann`, and `s.sleep`; `s.say` and `s.lead` need lines. The fake cursor stays hidden until the first `s.click` or `s.ann.moveTo`, so a scene that never clicks shows no pointer.

## Live command-line demos

`examples/terminal/` records a command as a browser-rendered terminal, which carries overlays and animation that a screen capture of a real terminal cannot. The recorder drives the page as for any web app; the scene is silent.

- `server.mjs [--runs <dir>] -- <command>` serves `index.html`. `GET /run` spawns the command and streams each stdout and stderr line, and each JSON line the command writes to fd 3, to the page as server-sent events. It records every item with its time offset to `<runs>/run-<ms>.jsonl`. `GET /run?replay=<file>` plays a recording back with its original timing and runs nothing. A second live run is refused without `--allow-many`, so a command with side effects runs once per server.
- The page plays items through one serial queue. A `{"event":"step","title","note"}` event switches the big step label and holds it `?hold=<ms>` (default 2000) before the next item plays, so a fast step stays readable while the terminal lines keep their real order.
- Replace `demo.sh` with the real command. It writes step events to fd 3 (`>&3` in a shell, `/dev/fd/3` as a file path); a CLI without that hook needs a flag or a wrapper that writes them. Write each step event a moment before the step's first output line: the two travel on separate pipes, so without the gap the line can arrive first.
- Take the live run once, then tune the hold and the page on `?replay=<file>` takes of its recording, which repeat without the command's side effects. Check animations on replay takes with `shot.mjs --action 'window.demo.start()' --at <s,...>` and `review.py --range`.
- A ligature font such as Fira Code turns `0x` into `0×`. Wrap the `x` in `<span style="font-variant-ligatures:none;font-feature-settings:'calt' 0">`; a zero-width non-joiner fixes `white-space: pre` blocks only. Its `--->` ligature draws an arrow of any length that matches the font.

## Review without watching

- `compose.py` reports frames kept, undecodable frames, and arrival lag. Expect 0 undecodable frames, or a few per page load. It warns when the tail was too short.
- `review.py` prints each line's start, speech length, slot, and dead air, and flags slots with more than 1.5 s of silence. Dead air after a lead-in usually means the action started too late (lower `at`) or the app is slow (trim the line before it instead).
- Without voice cues, `review.py` prints no table, and its sheet takes a still every 2 s (`--every <s>`), labelled with its time. To check an animation frame by frame, use `--range <a>:<b> --fps <n>`, with `--crop x,y,w,h` (video pixels) to keep only the part that moves.
- Open the contact sheet (`--sheet stills/sheet-v2.png`, a new name per version, because image viewers cache by path) and check each tile: the caption matches the line, the annotation points at the right element, nothing covers what the line talks about, and the numbers on screen match the narration.
- `--phonemes` output is the check on pronunciation; you cannot listen to the audio.

To re-cut after feedback, edit `script.json`, rerender only changed lines with `tts.py <dir> --only k1,k2`, and retake. Durations drive the scenes, so every audio change needs a new take.
