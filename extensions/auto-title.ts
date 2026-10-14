// Names an unnamed pi terminal session from its content. After the first finished agent run in the TUI, it asks a
// model for a short title and calls pi.setSessionName(); pi puts the name in the terminal title, so a Zed or other
// terminal tab shows it. It skips a session that already has a name (from /name or a host titling tool), and it
// never runs in RPC mode, where a host may own titling. `/auto-title` re-titles on demand, even over a set name.
// PI_AUTO_TITLE=0 turns off the automatic run. PI_AUTO_TITLE_MODEL=provider/id picks the model (default: session model).
// If this extension names the session first, a host titler may read that rename as manual and stop renaming.

const MAX_TITLE = 60;
const MAX_CHARS = 6000;

const normalize = (s: string) => s.replace(/\s+/gu, " ").trim();

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((b: any) => b?.type === "text" && typeof b.text === "string")
    .map((b: any) => b.text)
    .join(" ");
}

export function messages(entries: any[]): { role: "user" | "assistant"; text: string }[] {
  const out: { role: "user" | "assistant"; text: string }[] = [];
  for (const e of entries) {
    const role = e?.type === "message" ? e.message?.role : undefined;
    if (role !== "user" && role !== "assistant") continue;
    const text = normalize(textOf(e.message.content));
    if (text) out.push({ role, text });
  }
  return out;
}

export function cleanTitle(raw: string): string | undefined {
  let t = normalize(raw.split("\n").find((l) => l.trim()) ?? "")
    .replace(/^(title|name)\s*:\s*/i, "")
    .replace(/^["'`*#\s]+|["'`*\s]+$/gu, "")
    .replace(/[.:;,\s]+$/u, "");
  if (!t) return undefined;
  const chars = Array.from(t);
  if (chars.length > MAX_TITLE) t = chars.slice(0, MAX_TITLE - 3).join("").trimEnd() + "...";
  return t;
}

export function buildPrompt(msgs: { role: string; text: string }[]): string {
  const lines = msgs.map((m) => `${m.role === "user" ? "User" : "Assistant"}: ${m.text}`);
  let convo = "";
  for (const line of lines) {
    const room = MAX_CHARS - convo.length;
    if (room <= 0) break;
    convo += (convo ? "\n\n" : "") + Array.from(line).slice(0, Math.min(room, 1500)).join("");
  }
  return [
    "Write a title for this coding-agent session.",
    "Rules: 3 to 7 words, plain ASCII, sentence case, no quotes, no trailing punctuation.",
    "Name the concrete subject (component, symptom, or artifact), not the task type.",
    "Reply with the title only.",
    "",
    "<conversation>",
    convo,
    "</conversation>",
  ].join("\n");
}

export default function (pi: any) {
  let done = false;
  let running = false;

  pi.on("session_start", () => {
    done = false;
  });

  async function run(ctx: any, force: boolean): Promise<string | undefined> {
    if (running || !ctx.sessionManager?.getSessionFile?.()) return;
    const msgs = messages(ctx.sessionManager.getBranch());
    if (!msgs.some((m) => m.role === "user") || !msgs.some((m) => m.role === "assistant")) return;
    if (!force) {
      // One attempt per session: a failed model call is not retried on every run.
      done = true;
      if ((pi.getSessionName?.() ?? ctx.sessionManager.getSessionName?.() ?? "").trim()) return;
    }

    running = true;
    try {
      const spec = process.env.PI_AUTO_TITLE_MODEL;
      const model = spec?.includes("/")
        ? ctx.modelRegistry.find(spec.slice(0, spec.indexOf("/")), spec.slice(spec.indexOf("/") + 1))
        : ctx.model;
      if (!model || !ctx.modelRegistry.hasConfiguredAuth(model)) return;
      const res = await ctx.modelRegistry.complete(
        model,
        { messages: [{ role: "user", content: [{ type: "text", text: buildPrompt(msgs) }], timestamp: Date.now() }] },
        { cacheRetention: "none", maxTokens: 64 },
      );
      const title = cleanTitle(textOf(res.content));
      if (!title) return;
      pi.setSessionName(title);
      return title;
    } catch {
      // Best effort: a failed title must not affect the session.
    } finally {
      running = false;
    }
  }

  pi.on("agent_end", (_event: any, ctx: any) => {
    if (done || ctx.mode !== "tui" || process.env.PI_AUTO_TITLE === "0") return;
    void run(ctx, false);
  });

  pi.registerCommand("auto-title", {
    description: "Name this session from its content, replacing the current name",
    handler: async (_arg: string, ctx: any) => {
      const title = await run(ctx, true);
      ctx.ui.notify(title ? `Session named: ${title}` : "Could not generate a title", title ? "info" : "warning");
    },
  });
}
