// Example scene script. Copy it into the work dir and adapt the scenes.
// usage: DEMO_VIDEO_SKILL=<skill dir> PLAYWRIGHT_FROM=<project>/package.json node scenes.cjs <dir> <url>
const path = require("path");
const skill = process.env.DEMO_VIDEO_SKILL;
if (!skill) throw new Error("set DEMO_VIDEO_SKILL to the demo-video skill directory");
const { record } = require(path.join(skill, "scripts/recorder.cjs"));

const [dir, url] = process.argv.slice(2);
const tid = (id) => `[data-testid="${id}"]`;
const settled = (s, id) =>
  s.page.waitForFunction((sel) => !["none", "running"].includes(document.querySelector(sel).dataset.status), tid(`row-${id}`), { timeout: 30_000 });

record(
  {
    dir,
    url,
    viewport: { width: 1280, height: 800 },
    ready: (page) => page.waitForSelector(tid("limit")),
  },
  async (s) => {
    await s.sleep(0.6);
    await s.ann.card("DEMO", "Transfer limits", "🧪");
    await s.say("intro");

    await s.ann.ring(tid("row-small"));
    await s.lead("small-a", async () => {
      await s.click(tid("run-small"));
      await settled(s, "small");
    });
    await s.ann.clear();
    await s.ann.stamp(tid("row-small"), "SENT", "good");
    await s.say("small-b");

    await s.ann.clear();
    await s.ann.ring(tid("row-large"), "bad");
    await s.lead("v-large", async () => {
      await s.click(tid("run-large"));
      await settled(s, "large");
    });
    await s.ann.clear();
    await s.ann.stamp(tid("row-large"), "BLOCKED", "bad");
    const lim = await s.rect(tid("limit"));
    const limit = (await s.page.textContent(tid("limit"))).match(/\$[\d,]+/)[0];
    await s.ann.bubble(tid("limit"), `Limit is <b>${limit}</b>`, { x: lim.left + 160, y: lim.bottom + 70, tone: "bad" });
    await s.say("large-b");
    await s.sleep(1);
  },
).catch((e) => {
  console.error(e);
  process.exit(1);
});
