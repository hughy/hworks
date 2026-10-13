// `/hughy-mode on|off|status` (no argument toggles) keeps the hughy-router skill in force for a session.
// While on, every turn carries a short system-prompt section that points the model at the skill file,
// so routing survives compaction. The setting is stored in the session and restored on resume and fork.
// PI_HUGHY_MODE=1 starts new sessions with it on.

import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ENTRY = "hughy-mode";

const SKILL = (() => {
  try {
    return join(dirname(dirname(realpathSync(fileURLToPath(import.meta.url)))), "skills/hughy-router/SKILL.md");
  } catch {
    return "~/dev/hworks/skills/hughy-router/SKILL.md";
  }
})();

export const SECTION =
  `hughy-mode is on for this session. Before the first non-trivial engineering task, read ${SKILL} ` +
  "and follow it: route the task, state goal, effort, and verify in every brief, delegate writes to coder " +
  "with a gate, and end with the reply format it defines. Re-read it if you no longer have its text in " +
  "context. Questions, lookups, and one-line edits do not need a route.";

export default function (pi: any) {
  let enabled = process.env.PI_HUGHY_MODE === "1";

  const show = (ctx: any) => ctx.ui?.setStatus?.("hughy-mode", enabled ? "hughy-mode" : undefined);

  pi.on("session_start", (_event: any, ctx: any) => {
    const entries = ctx.sessionManager?.getBranch?.() ?? [];
    for (const e of entries) {
      if (e.type === "custom" && e.customType === ENTRY && typeof e.data?.enabled === "boolean") enabled = e.data.enabled;
    }
    show(ctx);
  });

  pi.registerCommand("hughy-mode", {
    description: "on|off|status: keep the hughy-router skill in force for this session (no argument toggles)",
    handler: async (arg: string, ctx: any) => {
      const a = (arg ?? "").trim();
      if (a === "status") {
        ctx.ui.notify(`hughy-mode is ${enabled ? "on" : "off"}`, "info");
        return;
      }
      if (a !== "" && a !== "on" && a !== "off") {
        ctx.ui.notify("usage: /hughy-mode [on|off|status]", "warning");
        return;
      }
      enabled = a === "" ? !enabled : a === "on";
      pi.appendEntry(ENTRY, { enabled });
      show(ctx);
      ctx.ui.notify(`hughy-mode ${enabled ? "on" : "off"} from the next turn`, "info");
    },
  });

  pi.on("before_agent_start", (event: any) => {
    const sections = event.systemPromptOptions?.sections;
    if (!sections) return;
    if (enabled) sections.hughy_mode = SECTION;
    else delete sections.hughy_mode;
  });
}
