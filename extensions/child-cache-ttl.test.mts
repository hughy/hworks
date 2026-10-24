const { default: install, isChildSession, shortenCacheTtl } = await import("./child-cache-ttl.ts");

let bad = 0;
const check = (name: string, ok: boolean, detail?: unknown) => { if (!ok) { bad++; console.log("FAIL", name, detail ?? ""); } };

const RUN = "11111111-2222-3333-4444-555555555555";
const child = `/h/.pi/agent/sessions/--w--/2026-10-24_abc/${RUN}/run-0/session.jsonl`;
const main = "/h/.pi/agent/sessions/--w--/2026-10-24_abc.jsonl";

check("child session", isChildSession(child));
check("main session", !isChildSession(main));
check("no session file", !isChildSession(undefined));
check("windows child path", isChildSession(child.replaceAll("/", "\\")));
check("run dir without session file", !isChildSession(`/s/${RUN}/run-0/other.jsonl`));

const long = { type: "ephemeral", ttl: "1h" };
const payload = {
  model: "claude",
  system: [{ type: "text", text: "sys", cache_control: long }],
  tools: [{ name: "a" }, { name: "b", cache_control: long }],
  messages: [
    { role: "user", content: "plain" },
    { role: "assistant", content: [{ type: "text", text: "ok" }] },
    { role: "user", content: [{ type: "tool_result", tool_use_id: "t", content: "r", cache_control: long }] },
  ],
};
const before = JSON.stringify(payload);
const out = shortenCacheTtl(payload);
check("payload left untouched", JSON.stringify(payload) === before);
check("system ttl dropped", JSON.stringify(out.system[0].cache_control) === '{"type":"ephemeral"}', out.system);
check("last tool ttl dropped", JSON.stringify(out.tools[1].cache_control) === '{"type":"ephemeral"}', out.tools);
check("last message ttl dropped", JSON.stringify(out.messages[2].content[0].cache_control) === '{"type":"ephemeral"}');
check("unmarked parts kept by reference", out.tools[0] === payload.tools[0] && out.messages[0] === payload.messages[0] && out.messages[1] === payload.messages[1]);
check("other fields kept", out.model === "claude");
check("no ttl anywhere", !JSON.stringify(out).includes("ttl"));

check("short retention unchanged", shortenCacheTtl({ system: [{ type: "text", text: "s", cache_control: { type: "ephemeral" } }], messages: [] }) === undefined);
check("openai payload unchanged", shortenCacheTtl({ model: "gpt", input: [], prompt_cache_key: "k" }) === undefined);
check("non-object unchanged", shortenCacheTtl(null) === undefined && shortenCacheTtl("x") === undefined);
check("absent keys not added", !("tools" in shortenCacheTtl({ system: [{ cache_control: long }] })));

const handlers: Record<string, any> = {};
const pi = { on: (name: string, fn: any) => { handlers[name] = fn; } };
const ctxFor = (file?: string) => ({ sessionManager: { getSessionFile: () => file } });
install(pi);
const hook = handlers["before_provider_request"];
check("hook registered", typeof hook === "function");
check("child payload shortened", !JSON.stringify(hook({ payload }, ctxFor(child))).includes("ttl"));
check("main payload untouched", hook({ payload }, ctxFor(main)) === undefined);
check("missing context untouched", hook({ payload }, undefined) === undefined);

{
  const old = process.env.PI_CHILD_CACHE_TTL;
  process.env.PI_CHILD_CACHE_TTL = "0";
  const off: Record<string, any> = {};
  install({ on: (name: string, fn: any) => { off[name] = fn; } });
  check("disabled by env", !off["before_provider_request"]);
  if (old === undefined) delete process.env.PI_CHILD_CACHE_TTL; else process.env.PI_CHILD_CACHE_TTL = old;
}

if (bad) { console.log(`${bad} check(s) failed`); process.exit(1); }
console.log("ok");
