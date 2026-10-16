#!/usr/bin/env node
// Screenshots pages of a running web app at several viewports and reports page overflow, one JSON line per shot.
// usage: PLAYWRIGHT_FROM=<project>/package.json node shot.mjs <base-url> [--path /a ...] [--viewports 1280x800,1920x1080]
//        [--wait-for <selector>] [--settle <ms>] [--timeout <ms>] [--local-storage key=<value> ...] [--full-page]
//        [--action <js>] [--at <s,s,...>] [--out <dir>] [--name <prefix>]
import { createRequire } from "node:module";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { parseArgs } from "node:util";

const require = createRequire(import.meta.url);
const { loadChromium } = require("./recorder.cjs");

const usage = `usage: node shot.mjs <base-url> [options]
  --path <p>              path to shoot, resolved against base-url; repeatable (default: base-url itself)
  --viewports <list>      comma-separated WxH sizes (default: 1280x800,1920x1080)
  --wait-for <selector>   wait until the selector is visible before the shot
  --settle <ms>           extra wait after load and selector (default: 500)
  --timeout <ms>          limit for page load, --wait-for, the measurement, and the screenshot (default: 30000)
  --local-storage k=v     set localStorage k to the text v before the page's scripts run; repeatable
  --full-page             capture the whole scrollable page instead of the viewport
  --action <js>           run this script in the page after load, --wait-for, and --settle, without waiting for it to finish
  --at <s,s,...>          shoot at these seconds after the action starts (after --settle without --action); one file per time
  --out <dir>             output directory (default: a new temp dir)
  --name <prefix>         file name prefix (default: none)
env: PLAYWRIGHT_FROM=<package.json whose project has playwright>, PLAYWRIGHT_CHANNEL=chrome|bundled (default: chrome)`;

function fail(msg) {
  console.error(`shot: ${msg}\n${usage}`);
  process.exit(2);
}

function intArg(name, raw) {
  if (!/^\d+$/.test(raw)) fail(`--${name} must be a whole number of milliseconds, got ${raw}`);
  return Number(raw);
}

function parseViewports(raw) {
  return raw.split(",").map((v) => {
    const m = /^(\d+)x(\d+)$/.exec(v.trim());
    if (!m || +m[1] === 0 || +m[2] === 0) throw new Error(`bad viewport ${JSON.stringify(v)}; use WxH such as 1280x800`);
    return { width: +m[1], height: +m[2] };
  });
}

function slugFor(p) {
  const slug = p.replace(/^[a-z][a-z0-9+.-]*:\/\/[^/]*/i, "").replace(/[^A-Za-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return slug || "root";
}

function parse(argv) {
  let parsed;
  try {
    parsed = parseArgs({
      args: argv,
      allowPositionals: true,
      options: {
        path: { type: "string", multiple: true },
        viewports: { type: "string", default: "1280x800,1920x1080" },
        "wait-for": { type: "string" },
        settle: { type: "string", default: "500" },
        timeout: { type: "string", default: "30000" },
        "local-storage": { type: "string", multiple: true },
        "full-page": { type: "boolean", default: false },
        action: { type: "string" },
        at: { type: "string" },
        out: { type: "string" },
        name: { type: "string", default: "" },
        help: { type: "boolean", short: "h", default: false },
      },
    });
  } catch (e) {
    fail(e.message);
  }
  const { values: o, positionals } = parsed;
  if (o.help) {
    console.log(usage);
    process.exit(0);
  }
  if (positionals.length !== 1) fail("expected exactly one base URL");
  let base;
  try {
    base = new URL(positionals[0]);
  } catch {
    fail(`not a URL: ${positionals[0]}`);
  }
  let viewports;
  try {
    viewports = parseViewports(o.viewports);
  } catch (e) {
    fail(e.message);
  }
  let at = null;
  if (o.at !== undefined) {
    at = o.at.split(",").map((v) => (/^\d+(\.\d+)?$/.test(v.trim()) ? Number(v) : NaN));
    if (at.some(Number.isNaN)) fail(`--at wants seconds such as 0.5,2,6, got ${o.at}`);
    if (new Set(at).size !== at.length) fail(`--at lists a time twice: ${o.at}`);
  }
  const storage = (o["local-storage"] || []).map((kv) => {
    const i = kv.indexOf("=");
    if (i <= 0) fail(`--local-storage wants key=value, got ${kv}`);
    return [kv.slice(0, i), kv.slice(i + 1)];
  });
  const paths = o.path || [""];
  const targets = paths.map((p) => ({ path: p || base.pathname, url: new URL(p, base).href, slug: slugFor(p || base.pathname) }));
  const seen = new Map();
  for (const t of targets) {
    if (seen.has(t.slug)) fail(`paths ${seen.get(t.slug)} and ${t.path} both map to file name ${t.slug}`);
    seen.set(t.slug, t.path);
  }
  return {
    base,
    targets,
    viewports,
    waitFor: o["wait-for"],
    settle: intArg("settle", o.settle),
    timeout: intArg("timeout", o.timeout),
    storage,
    fullPage: o["full-page"],
    action: o.action,
    at,
    out: path.resolve(o.out || fs.mkdtempSync(path.join(os.tmpdir(), "shot-"))),
    name: o.name,
  };
}

const firstLine = (e) => String((e && e.message) || e).split("\n")[0];

function measure() {
  return {
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    scrollHeight: document.documentElement.scrollHeight,
    innerHeight: window.innerHeight,
  };
}

function withTimeout(promise, ms) {
  let timer;
  const expired = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`timed out after ${ms} ms`)), ms);
  });
  return Promise.race([promise, expired]).finally(() => clearTimeout(timer));
}

// Returns one result per shot: one normally, one per --at time otherwise.
async function shoot(browser, opts, target, viewport) {
  const size = `${viewport.width}x${viewport.height}`;
  const stem = `${opts.name}${target.slug}-${size}`;
  const results = [];
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  try {
    if (opts.storage.length) {
      // Init scripts run in every frame, including about:blank and cross-origin iframes, where storage is another origin's or throws.
      await context.addInitScript(
        ([origin, entries]) => {
          if (location.origin !== origin) return;
          try {
            for (const [k, v] of entries) localStorage.setItem(k, v);
          } catch {}
        },
        [new URL(target.url).origin, opts.storage],
      );
    }
    const page = await context.newPage();
    const consoleErrors = [];
    page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
    page.on("pageerror", (e) => consoleErrors.push(String(e.message || e)));
    const errors = [];
    let capture = true;
    let response;
    try {
      response = await page.goto(target.url, { waitUntil: "load", timeout: opts.timeout });
    } catch (e) {
      errors.push(`load failed: ${firstLine(e)}`);
      // After a timeout the page shows what has rendered so far, but only if the main document arrived; otherwise the
      // page is still about:blank. Other failures leave only Chrome's error page.
      capture = e.name === "TimeoutError" && page.url() !== "about:blank";
    }
    if (response && response.status() >= 400) errors.push(`HTTP ${response.status()}`);
    if (!errors.length && opts.waitFor) {
      try {
        await page.waitForSelector(opts.waitFor, { state: "visible", timeout: opts.timeout });
      } catch {
        errors.push(`selector ${opts.waitFor} not visible after ${opts.timeout} ms`);
      }
    }
    if (!errors.length && opts.settle) await page.waitForTimeout(opts.settle);
    let t0 = Date.now();
    if (!errors.length && opts.action) {
      try {
        // Deferred, so a long-running action does not hold up the first timed shot.
        await withTimeout(page.evaluate((code) => void setTimeout(() => (0, eval)(code), 0), opts.action), opts.timeout);
        t0 = Date.now();
      } catch (e) {
        errors.push(`action failed: ${firstLine(e)}`);
      }
    }
    const times = opts.at && !errors.length ? opts.at : [null];
    for (const at of times) {
      const result = { path: target.path, viewport: size, file: null, consoleErrors };
      const errs = [...errors];
      const file = path.join(opts.out, at === null ? `${stem}.png` : `${stem}-t${at}.png`);
      if (at !== null) {
        result.at = at;
        await page.waitForTimeout(Math.max(0, at * 1000 - (Date.now() - t0)));
      }
      if (capture) {
        try {
          // page.evaluate has no timeout of its own and never returns while the page's main thread is busy.
          Object.assign(result, await withTimeout(page.evaluate(measure), opts.timeout));
          result.overflowX = result.scrollWidth > result.innerWidth;
          result.overflowY = result.scrollHeight > result.innerHeight;
        } catch (e) {
          errs.push(`measure failed: ${firstLine(e)}`);
        }
        try {
          await page.screenshot({ path: file, fullPage: opts.fullPage, timeout: opts.timeout });
          result.file = file;
        } catch (e) {
          errs.push(`screenshot failed: ${firstLine(e)}`);
        }
      }
      if (errs.length) result.error = errs.join("; ");
      results.push(result);
    }
    return results;
  } finally {
    await context.close().catch(() => {});
  }
}

async function main() {
  const opts = parse(process.argv.slice(2));
  fs.mkdirSync(opts.out, { recursive: true });
  let chromium;
  try {
    chromium = loadChromium(process.env.PLAYWRIGHT_FROM);
  } catch (e) {
    console.error(`shot: ${e.message}`);
    process.exit(1);
  }
  const channel = process.env.PLAYWRIGHT_CHANNEL || "chrome";
  let browser;
  try {
    browser = await chromium.launch(channel === "bundled" ? {} : { channel });
  } catch (e) {
    console.error(`shot: cannot launch ${channel === "bundled" ? "Playwright's Chromium" : `the ${channel} channel`}: ${firstLine(e)}`);
    process.exit(1);
  }
  const failures = [];
  let shots = 0;
  try {
    for (const target of opts.targets) {
      for (const viewport of opts.viewports) {
        const rs = await shoot(browser, opts, target, viewport).catch((e) => [
          { path: target.path, viewport: `${viewport.width}x${viewport.height}`, error: firstLine(e) },
        ]);
        shots += rs.length;
        for (const r of rs) {
          const line = {};
          for (const k of ["path", "viewport", "file", "scrollWidth", "innerWidth", "scrollHeight", "innerHeight", "overflowX", "overflowY", "consoleErrors"]) line[k] = r[k] ?? null;
          if (r.at !== undefined) line.at = r.at;
          if (r.error) line.error = r.error;
          console.log(JSON.stringify(line));
          if (r.error) failures.push(`${target.url} at ${r.viewport}${r.at === undefined ? "" : ` t=${r.at}`}: ${r.error}`);
        }
      }
    }
  } finally {
    await browser.close();
  }
  console.error(`shot: ${shots - failures.length} ok, ${failures.length} failed, files in ${opts.out}`);
  for (const f of failures) console.error(`shot: FAILED ${f}`);
  process.exit(failures.length ? 1 : 0);
}

await main();
