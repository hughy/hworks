delete process.env.PI_AUTO_TITLE_MODEL;
delete process.env.PI_AUTO_TITLE;
const { default: register, messages, cleanTitle, buildPrompt } = await import("./auto-title.ts");

let bad = 0;
const check = (name: string, ok: boolean, detail?: unknown) => { if (!ok) { bad++; console.log("FAIL", name, detail ?? ""); } };

check("clean strips quotes and period", cleanTitle('"Fix flaky auth test."') === "Fix flaky auth test");
check("clean strips label", cleanTitle("Title: Zed thread naming") === "Zed thread naming");
check("clean takes first line", cleanTitle("\n\nA title\nextra") === "A title");
check("clean caps length", Array.from(cleanTitle("word ".repeat(40))!).length <= 60);
check("clean empty", cleanTitle(" \n ") === undefined);

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
    mode: opts.mode ?? "tui",
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
await a.end();
check("names once", a.state.completes === 1);

const c = make({ name: "My chosen name" });
await c.end();
check("keeps existing name", c.state.completes === 0 && c.state.names.length === 0, c.state);
await c.end();
check("does not recheck after skipping", c.state.completes === 0);
await c.command().handler("", c.ctx);
check("/auto-title overrides existing name", c.state.names.join() === "Zed thread naming" && c.state.notes.at(-1)!.includes("Zed thread naming"), c.state);

const d = make({ file: undefined });
await d.end();
check("skips unpersisted session", d.state.completes === 0);
const e = make({ mode: "rpc" });
await e.end();
check("skips rpc mode", e.state.completes === 0);
await e.command().handler("", e.ctx);
check("/auto-title works in rpc mode", e.state.names.join() === "Zed thread naming", e.state);
const p = make({ mode: "print" });
await p.end();
check("skips print mode", p.state.completes === 0);
const f = make({ model: null });
await f.end();
check("skips without model", f.state.completes === 0 && f.state.names.length === 0);

process.env.PI_AUTO_TITLE = "0";
const g = make();
await g.end();
check("PI_AUTO_TITLE=0 turns it off", g.state.completes === 0);
delete process.env.PI_AUTO_TITLE;

const r = make();
r.h.session_start({}, r.ctx);
await r.end();
check("new session titles again", r.state.completes === 1);

console.log(bad ? `${bad} failures` : "all pass");
process.exit(bad ? 1 : 0);
