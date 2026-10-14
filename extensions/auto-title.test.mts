delete process.env.PI_AUTO_TITLE;
delete process.env.PI_AUTO_TITLE_MODEL;
const { default: register, messages, promptTitle, canReplace, cleanTitle, buildPrompt } = await import("./auto-title.ts");

let bad = 0;
const check = (name: string, ok: boolean, detail?: unknown) => { if (!ok) { bad++; console.log("FAIL", name, detail ?? ""); } };

check("clean strips quotes and period", cleanTitle('"Fix flaky auth test."') === "Fix flaky auth test");
check("clean strips label", cleanTitle("Title: Zed thread naming") === "Zed thread naming");
check("clean takes first line", cleanTitle("\n\nA title\nextra") === "A title");
check("clean caps length", Array.from(cleanTitle("word ".repeat(40))!).length <= 60);
check("clean empty", cleanTitle(" \n ") === undefined);

const long = "fix   the\nbug " + "x".repeat(200);
check("promptTitle matches pi-acp", promptTitle(long) === Array.from("fix the bug " + "x".repeat(200)).slice(0, 80).join(""));
check("replace empty", canReplace(undefined, "hi", undefined) && canReplace("  ", "hi", undefined));
check("replace first-prompt name", canReplace(promptTitle(long), long, undefined));
check("replace own name", canReplace("Old auto", "hi", "Old auto"));
check("keep user name", !canReplace("My name", "hi", "Old auto"));
check("keep user name without ours", !canReplace("My name", "hi", undefined));

const entries = [
  { type: "message", message: { role: "user", content: [{ type: "text", text: "rename  threads" }] } },
  { type: "message", message: { role: "toolResult", content: "x" } },
  { type: "message", message: { role: "assistant", content: [{ type: "thinking", thinking: "t" }, { type: "text", text: "ok" }] } },
  { type: "custom" },
];
const m = messages(entries);
check("messages filters", m.length === 2 && m[0].text === "rename threads" && m[1].text === "ok", m);
check("prompt carries conversation", buildPrompt(m).includes("User: rename threads") && buildPrompt(m).includes("Assistant: ok"));
check("prompt is bounded", buildPrompt([{ role: "user", text: "y".repeat(100000) }]).length < 8000);

function make(opts: { name?: string; file?: string | undefined; reply?: string; mode?: string; model?: any } = {}) {
  const h: Record<string, any> = {};
  let command: any;
  const state = { name: opts.name as string | undefined, entries: [] as any[], names: [] as string[], completes: 0, notes: [] as string[] };
  register({
    on(n: string, fn: any) { h[n] = fn; },
    registerCommand(_n: string, c: any) { command = c; },
    appendEntry(t: string, data: any) { state.entries.push({ type: "custom", customType: t, data }); },
    setSessionName(n: string) { state.name = n; state.names.push(n); },
    getSessionName: () => state.name,
  });
  const model = opts.model === undefined ? { id: "m" } : opts.model;
  const ctx = {
    mode: opts.mode ?? "rpc",
    model,
    sessionManager: {
      getSessionFile: () => ("file" in opts ? opts.file : "/tmp/s.jsonl"),
      getBranch: () => [...entries, ...state.entries],
      getSessionName: () => state.name,
    },
    modelRegistry: {
      find: () => undefined,
      hasConfiguredAuth: () => true,
      complete: async () => { state.completes++; return { content: [{ type: "text", text: opts.reply ?? "Zed thread naming" }] }; },
    },
    ui: { notify: (msg: string) => state.notes.push(msg) },
  };
  h.session_start({}, ctx);
  const end = async () => { h.agent_end({}, ctx); await new Promise((r) => setTimeout(r, 10)); };
  return { h, ctx, state, end, command: () => command };
}

const a = make();
await a.end();
check("names after first run", a.state.names.join() === "Zed thread naming" && a.state.completes === 1, a.state);
check("records entry", a.state.entries[0]?.data.title === "Zed thread naming");
await a.end();
check("names once", a.state.completes === 1);

const b = make({ name: "rename threads" });
await b.end();
check("replaces first-prompt name", b.state.names.length === 1, b.state);

const c = make({ name: "My chosen name" });
await c.end();
check("keeps user name", c.state.completes === 0 && c.state.names.length === 0, c.state);
await c.command().handler("", c.ctx);
check("/auto-title overrides user name", c.state.names.join() === "Zed thread naming" && c.state.notes.at(-1)!.includes("Zed thread naming"), c.state);

const d = make({ file: undefined });
await d.end();
check("skips unpersisted session", d.state.completes === 0);
const e = make({ mode: "print" });
await e.end();
check("skips print mode", e.state.completes === 0);
const f = make({ model: null });
await f.end();
check("skips without model", f.state.completes === 0 && f.state.names.length === 0);

process.env.PI_AUTO_TITLE = "0";
const g = make();
await g.end();
check("PI_AUTO_TITLE=0 disables", g.state.completes === 0);
delete process.env.PI_AUTO_TITLE;

const r = make();
r.h.session_start({}, { ...r.ctx, sessionManager: { ...r.ctx.sessionManager, getBranch: () => [...entries, { type: "custom", customType: "auto-title", data: { title: "Done" } }] } });
await r.end();
check("resume does not re-title", r.state.completes === 0);

console.log(bad ? `${bad} failures` : "all pass");
process.exit(bad ? 1 : 0);
