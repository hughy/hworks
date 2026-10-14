// Names a pi session from its content so clients that show the name (Zed via pi-acp, `/resume`) stop showing the
// first prompt. After the first finished agent run, it asks a model for a short title and calls pi.setSessionName().
// It is off unless PI_AUTO_TITLE=1: a host-managed extension may already title sessions, and such an extension can
// read any rename it did not make as a manual one and stop. Enable it only where that titling never runs, such as
// Zed via pi-acp, which names every new session from its first prompt (set the flag in the Zed agent_servers entry).
// It only replaces a name that is empty, that it set itself, or that is the first-prompt title pi-acp sets, so a
// name you set with /name stays. `/auto-title` re-titles on demand, even over a name you set, with or without the flag.
// PI_AUTO_TITLE_MODEL=provider/id picks the model (default: the session model).

const ENTRY = "auto-title";
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

// pi-acp names a new session with the first 80 characters of the first prompt.
export function promptTitle(text: string): string {
  return Array.from(normalize(text)).slice(0, 80).join("");
}

export function canReplace(current: string | undefined, firstUser: string | undefined, ours: string | undefined): boolean {
  const name = (current ?? "").trim();
  if (!name) return true;
  if (ours && name === ours) return true;
  return !!firstUser && name === promptTitle(firstUser);
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
  let titled = false;
  let running = false;
  let ours: string | undefined;

  pi.on("session_start", (_event: any, ctx: any) => {
    titled = false;
    ours = undefined;
    for (const e of ctx.sessionManager?.getBranch?.() ?? []) {
      if (e.type === "custom" && e.customType === ENTRY && typeof e.data?.title === "string") {
        titled = true;
        ours = e.data.title;
      }
    }
  });

  async function run(ctx: any, force: boolean): Promise<string | undefined> {
    if (running || !ctx.sessionManager?.getSessionFile?.()) return;
    const msgs = messages(ctx.sessionManager.getBranch());
    const firstUser = msgs.find((m) => m.role === "user")?.text;
    if (!firstUser || !msgs.some((m) => m.role === "assistant")) return;
    if (!force && !canReplace(pi.getSessionName?.() ?? ctx.sessionManager.getSessionName?.(), firstUser, ours)) {
      titled = true;
      return;
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
      pi.appendEntry(ENTRY, { title });
      ours = title;
      titled = true;
      return title;
    } catch {
      // Best effort: a failed title must not affect the session.
    } finally {
      running = false;
    }
  }

  pi.on("agent_end", (_event: any, ctx: any) => {
    if (process.env.PI_AUTO_TITLE !== "1" || titled || (ctx.mode !== "tui" && ctx.mode !== "rpc")) return;
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
