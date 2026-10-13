import { existsSync } from "node:fs";

delete process.env.PI_HUGHY_MODE;
const { SECTION, default: register } = await import("./hughy-mode.ts");

let bad = 0;
const check = (name: string, ok: boolean, detail?: unknown) => { if (!ok) { bad++; console.log("FAIL", name, detail ?? ""); } };

function make(branch: any[] = []) {
  const h: Record<string, any> = {};
  let command: any;
  const entries: any[] = [];
  const notes: string[] = [];
  let status: any = "unset";
  register({
    on(n: string, fn: any) { h[n] = fn; },
    registerCommand(_n: string, c: any) { command = c; },
    appendEntry(t: string, data: any) { entries.push({ type: "custom", customType: t, data }); },
  });
  const ctx = { sessionManager: { getBranch: () => branch }, ui: { notify: (m: string) => notes.push(m), setStatus: (_k: string, v: any) => { status = v; } } };
  h.session_start({}, ctx);
  const turn = () => { const e = { systemPromptOptions: { sections: {} as Record<string, string> } }; h.before_agent_start(e, ctx); return e.systemPromptOptions.sections; };
  return { run: (a: string) => command.handler(a, ctx), turn, entries, notes, status: () => status };
}

const path = SECTION.match(/read (\S+SKILL\.md)/)?.[1];
check("skill path exists", !!path && existsSync(path), path);

const s = make();
check("off by default", !("hughy_mode" in s.turn()));
await s.run("on");
check("on injects section", s.turn().hughy_mode === SECTION);
check("on sets status", s.status() === "hughy-mode");
await s.run("");
check("bare command toggles off", !("hughy_mode" in s.turn()));
check("off clears status", s.status() === undefined);
await s.run("");
check("bare command toggles on", "hughy_mode" in s.turn());
await s.run("bogus");
check("bad arg leaves state", "hughy_mode" in s.turn() && s.notes.at(-1)!.startsWith("usage"));
check("entries persisted", s.entries.map((e) => e.data.enabled).join() === "true,false,true", s.entries);

const r = make([...s.entries, { type: "message" }]);
check("resume restores on", "hughy_mode" in r.turn());
const r2 = make([{ type: "custom", customType: "hughy-mode", data: { enabled: true } }, { type: "custom", customType: "hughy-mode", data: { enabled: false } }]);
check("resume uses last entry", !("hughy_mode" in r2.turn()));

console.log(bad ? `${bad} failures` : "all pass");
process.exit(bad ? 1 : 0);
