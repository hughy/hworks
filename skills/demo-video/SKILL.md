---
name: demo-video
description: Record a short demo, walkthrough, or scenario video, narrated or silent, of a running web app or a live command-line run, or re-cut one after feedback on voice, wording, pacing, or length. Also screenshot a running web UI at several viewports and check for overflow, without a video.
---

# demo-video

Paths below are relative to this skill's directory; pass them as absolute paths.

- `scripts/shot.mjs <base-url>` screenshots pages at several viewports and reports overflow, with no video (see Screenshots).
- `tests/shot.sh` checks `shot.mjs` on static pages.

Playwright comes from the project under demo: set `PLAYWRIGHT_FROM=<project>/package.json` (any package.json whose project resolves `playwright`, `playwright-core`, or `@playwright/test`). A project with none, such as a Go repo: run `npm i playwright-core` in a scratch dir and point `PLAYWRIGHT_FROM` at its `package.json`. The recorder and `shot.mjs` launch installed Chrome by default; set `PLAYWRIGHT_CHANNEL=bundled` to use Playwright's browser instead.

## Screenshots

For UI review, use `scripts/shot.mjs` instead of writing a one-off Playwright script. It needs only `node` and the Playwright setup above, not `setup.sh`.

```sh
PLAYWRIGHT_FROM=<project>/package.json node scripts/shot.mjs http://localhost:3000 \
  --path / --path /settings --viewports 1280x800,1920x1080 \
  --wait-for '[data-testid="app"]' --settle 500 \
  --local-storage 'prefs={"theme":"dark"}' --out "$TASK_DIR/shots" --name before-
```

- It writes `<name><slug>-<w>x<h>.png` per path and viewport, where the slug is the path with each run of non-alphanumeric characters turned into `-` (`/` is `root`). Without `--out` it writes to a new temp dir and prints the dir on stderr.
- Each shot prints one JSON line on stdout: `path`, `viewport`, `file`, `scrollWidth`, `innerWidth`, `scrollHeight`, `innerHeight`, `overflowX`, `overflowY`, and `consoleErrors` (console errors and uncaught exceptions). `overflowX` true means the page scrolls sideways at that width, which is usually a layout bug.
- `--local-storage key=value` stores `value` as given, before the page's scripts run, on the shot page's origin only. Pass JSON text when the app parses the key as JSON.
- Each shot gets a fresh browser context, so storage one page writes does not leak into the next.
- `--wait-for` waits until the selector is visible; `--settle` then waits a fixed time for animations and fonts. `--timeout` (default 30000 ms) limits the load, the wait, the measurement, and the screenshot. `--full-page` captures the whole page instead of the viewport.
- To shoot a page mid-run or mid-animation, pass `--action <js>` (started, not awaited, such as `'window.demo.start()'`) and `--at <s,...>` (seconds after it starts). Each time gets its own `-t<s>` file and JSON line.
- It exits 1 if any shot fails (load, HTTP status of 400 or above, selector, measure, or capture), naming each on stderr and going on; that shot's JSON line has an `error` field, and `file` is null when no PNG was written. It exits 2 on bad arguments. `node scripts/shot.mjs --help` lists every option.

## Video

To record or re-cut a video, read `references/video.md`: the workflow, silent and live command-line videos, the `script.json` format, the scene helpers, why frames carry a clock strip, and how to review a take without watching it.
