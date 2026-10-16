// Silent scene script for the terminal page: start the stream, wait for the run to finish, hold the last frame.
// usage: DEMO_VIDEO_SKILL=<skill dir> PLAYWRIGHT_FROM=<project>/package.json node scenes.cjs <dir> <url>
// <url> is the server's page, e.g. http://127.0.0.1:4173/?replay=run-1.jsonl&hold=2500. Without ?replay= it runs the command live.
// The work dir needs no script.json or audio.
const path = require("path");
const skill = process.env.DEMO_VIDEO_SKILL;
if (!skill) throw new Error("set DEMO_VIDEO_SKILL to the demo-video skill directory");
const { record } = require(path.join(skill, "scripts/recorder.cjs"));

const [dir, url] = process.argv.slice(2);
record(
  {
    dir,
    url,
    viewport: { width: 1280, height: 720 },
    tail: 5,
    ready: (page) => page.waitForFunction(() => document.body.dataset.ready === "1"),
  },
  async (s) => {
    await s.sleep(1);
    await s.page.evaluate(() => window.demo.start());
    await s.page.waitForFunction(() => ["done", "failed"].includes(document.body.dataset.state), null, { timeout: 600_000 });
    if ((await s.page.evaluate(() => document.body.dataset.state)) !== "done") throw new Error("the run failed; see the terminal pane");
    await s.sleep(2);
  },
).catch((e) => {
  console.error(e);
  process.exit(1);
});
