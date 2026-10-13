#!/usr/bin/env node
// Screenshots pages of a running web app at several viewports and reports page overflow, one JSON line per shot.
// usage: PLAYWRIGHT_FROM=<project>/package.json node shot.mjs <base-url> [--path /a ...] [--viewports 1280x800,1920x1080]
//        [--wait-for <selector>] [--settle <ms>] [--timeout <ms>] [--local-storage key=<value> ...] [--full-page]
//        [--out <dir>] [--name <prefix>]
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
  --timeout <ms>          limit for page load, --wait-for, and the screenshot (default: 30000)
  --local-storage k=v     set localStorage k to the text v before the page's scripts run; repeatable
  --full-page             capture the whole scrollable page instead of the viewport
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
    out: path.resolve(o.out || fs.mkdtempSync(path.join(os.tmpdir(), "shot-"))),
    name: o.name,
  };
}

async function shoot(browser, opts, target, viewport) {
  const size = `${viewport.width}x${viewport.height}`;
  const file = path.join(opts.out, `${opts.name}${target.slug}-${size}.png`);
  const result = { path: target.path, viewport: size, file: null, consoleErrors: [] };
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
    page.on("console", (m) => m.type() === "error" && result.consoleErrors.push(m.text()));
    page.on("pageerror", (e) => result.consoleErrors.push(String(e.message || e)));
    let response;
    try {
      response = await page.goto(target.url, { waitUntil: "load", timeout: opts.timeout });
    } catch (e) {
      result.error = `load failed: ${e.message.split("\n")[0]}`;
      return result;
    }
    if (response && response.status() >= 400) result.error = `HTTP ${response.status()}`;
    if (!result.error && opts.waitFor) {
      try {
        await page.waitForSelector(opts.waitFor, { state: "visible", timeout: opts.timeout });
      } catch {
        result.error = `selector ${opts.waitFor} not visible after ${opts.timeout} ms`;
      }
    }
    if (!result.error && opts.settle) await page.waitForTimeout(opts.settle);
    try {
      Object.assign(
        result,
        await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
          scrollHeight: document.documentElement.scrollHeight,
          innerHeight: window.innerHeight,
        })),
      );
      result.overflowX = result.scrollWidth > result.innerWidth;
      result.overflowY = result.scrollHeight > result.innerHeight;
      // A failed shot still saves what rendered, which usually shows why the selector never appeared.
      await page.screenshot({ path: file, fullPage: opts.fullPage, timeout: opts.timeout });
      result.file = file;
    } catch (e) {
      result.error ??= `screenshot failed: ${e.message.split("\n")[0]}`;
    }
    return result;
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
    console.error(`shot: cannot launch ${channel === "bundled" ? "Playwright's Chromium" : `the ${channel} channel`}: ${e.message.split("\n")[0]}`);
    process.exit(1);
  }
  const failures = [];
  try {
    for (const target of opts.targets) {
      for (const viewport of opts.viewports) {
        const r = await shoot(browser, opts, target, viewport).catch((e) => ({
          path: target.path,
          viewport: `${viewport.width}x${viewport.height}`,
          error: e.message.split("\n")[0],
        }));
        const line = {};
        for (const k of ["path", "viewport", "file", "scrollWidth", "innerWidth", "scrollHeight", "innerHeight", "overflowX", "overflowY", "consoleErrors"]) line[k] = r[k] ?? null;
        if (r.error) line.error = r.error;
        console.log(JSON.stringify(line));
        if (r.error) failures.push(`${target.url} at ${r.viewport}: ${r.error}`);
      }
    }
  } finally {
    await browser.close();
  }
  console.error(`shot: ${opts.targets.length * opts.viewports.length - failures.length} ok, ${failures.length} failed, files in ${opts.out}`);
  for (const f of failures) console.error(`shot: FAILED ${f}`);
  process.exit(failures.length ? 1 : 0);
}

await main();
