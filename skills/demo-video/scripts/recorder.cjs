// Records a live web page with annotations and a voice-cue log. A scene script calls record(opts, scenes).
// Reads <dir>/script.json and <dir>/audio/durations.json (from tts.py) when they exist; a silent video needs neither.
// Writes <dir>/frames/ and <dir>/timeline.json.
const { createRequire } = require("module");
const fs = require("fs");
const path = require("path");

const sleep = (s) => new Promise((res) => setTimeout(res, s * 1000));
const now = () => Date.now() / 1000;

function loadChromium(from) {
  const req = from ? createRequire(path.resolve(from)) : require;
  for (const name of ["playwright", "playwright-core", "@playwright/test"]) {
    try {
      return req(name).chromium;
    } catch {}
  }
  throw new Error("recorder: Playwright not found. Set PLAYWRIGHT_FROM to a package.json whose project has playwright installed.");
}

// Picks the voice for a line key: the first voice whose prefix matches, else the voice without a prefix.
function voiceFor(voices, key) {
  const entries = Object.entries(voices);
  const hit = entries.find(([, v]) => v.prefix && key.startsWith(v.prefix)) || entries.find(([, v]) => !v.prefix);
  if (!hit) throw new Error(`recorder: no voice for line ${key}`);
  return { name: hit[0], ...hit[1] };
}

async function record(opts, scenes) {
  const {
    dir: rawDir,
    url,
    viewport = { width: 1440, height: 900 },
    scale = 2,
    channel = process.env.PLAYWRIGHT_CHANNEL || "chrome",
    ready = async () => {},
    theme = {},
    tail = 25,
    quality = 88,
  } = opts;
  const dir = path.resolve(rawDir);
  const readJson = (file, none) => (fs.existsSync(path.join(dir, file)) ? JSON.parse(fs.readFileSync(path.join(dir, file), "utf8")) : none);
  const script = readJson("script.json", { voices: {}, lines: {} });
  const durations = readJson("audio/durations.json", {});
  for (const key of Object.keys(script.lines)) if (!(key in durations)) throw new Error(`recorder: no audio for ${key}; rerun tts.py`);
  const framesDir = path.join(dir, "frames");
  fs.rmSync(framesDir, { recursive: true, force: true });
  fs.mkdirSync(framesDir, { recursive: true });

  const chromium = loadChromium(process.env.PLAYWRIGHT_FROM);
  // Without the flag the screencast emits CSS-pixel frames whatever deviceScaleFactor says.
  const args = [`--force-device-scale-factor=${scale}`];
  const browser = await chromium.launch(channel === "bundled" ? { args } : { channel, args });
  const frames = [];
  const cues = [];
  try {
    // bypassCSP: the overlay's stylesheet is inline, which a strict style-src would block.
    const context = await browser.newContext({ viewport, deviceScaleFactor: scale, bypassCSP: true });
    const clock = { base: Date.now(), cells: 26, cellW: 8, height: 6 };
    // An init script survives navigation: every new page gets the overlay and clock strip once its body exists.
    const overlay = fs.readFileSync(path.join(__dirname, "overlay.js"), "utf8");
    await context.addInitScript({ content: `window.__annClock=${JSON.stringify(clock)};window.__annTheme=${JSON.stringify(theme)};\n${overlay}` });
    const page = await context.newPage();
    await page.goto(url);
    await ready(page);

    const cdp = await context.newCDPSession(page);
    cdp.on("Page.screencastFrame", ({ data, metadata, sessionId }) => {
      const file = path.join(framesDir, `${String(frames.length).padStart(6, "0")}.jpg`);
      fs.writeFileSync(file, Buffer.from(data, "base64"));
      frames.push({ file, t: metadata.timestamp });
      cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
    });
    await cdp.send("Page.startScreencast", {
      format: "jpeg",
      quality,
      maxWidth: viewport.width * scale,
      maxHeight: viewport.height * scale,
      everyNthFrame: 1,
    });

    // Waits for the overlay, which is briefly absent while a new page loads.
    const ann = new Proxy({}, {
      get: (_, fn) => async (...args) => {
        await page.waitForFunction(() => window.ann, null, { timeout: 10_000 });
        return page.evaluate(([fn, args]) => window.ann[fn](...args), [fn, args]);
      },
    });
    const s = {
      page,
      ann,
      lines: script.lines,
      durations,
      sleep,
      rect: (sel) => page.evaluate((sel) => document.querySelector(sel).getBoundingClientRect().toJSON(), sel),
      sfx(file, gain = 0.35) {
        cues.push({ kind: "sfx", file: path.resolve(file), gain, t: now() });
      },
      // Shows the line's caption and logs its voice cue; resolves when the audio would end.
      async say(key) {
        if (!(key in script.lines)) throw new Error(`recorder: unknown line ${key}`);
        const v = voiceFor(script.voices, key);
        await ann.caption(script.lines[key], { label: v.label || "", alt: !!v.alt });
        cues.push({ kind: "voice", key, file: path.join(dir, "audio", `${key}.wav`), t: now() });
        await sleep(durations[key]);
      },
      // Speaks a line and starts `action` partway through it, so the app's latency overlaps speech. Resolves when both finish.
      async lead(key, action, at = 0.4) {
        const spoken = s.say(key);
        await sleep(Math.max(0.2, durations[key] * at));
        await Promise.all([action(), spoken]);
      },
      // Moves the fake cursor to the element, shows a click ripple, then clicks it for real.
      async click(sel, { travel = 0.7 } = {}) {
        await ann.moveTo(sel);
        await sleep(travel);
        await ann.click();
        await page.click(sel);
      },
    };

    await scenes(s);
    const end = now();
    // Screencast frames can arrive seconds late; keep capturing until frames drawn before `end` have landed.
    await sleep(tail);
    await cdp.send("Page.stopScreencast");
    await sleep(0.5);
    const timeline = { frames, cues, end, clock: { ...clock, base: clock.base / 1000 }, viewport, scale };
    fs.writeFileSync(path.join(dir, "timeline.json"), JSON.stringify(timeline, null, 1));
    console.log(cues.length ? `recorder: ${frames.length} frames, ${(end - cues[0].t).toFixed(1)}s from first cue` : `recorder: ${frames.length} frames, no cues`);
    return timeline;
  } finally {
    await browser.close();
  }
}

module.exports = { record, voiceFor, sleep, loadChromium };
