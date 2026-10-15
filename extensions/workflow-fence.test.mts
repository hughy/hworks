import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

process.env.TMPDIR = mkdtempSync(join(tmpdir(), "workflow-fence-test-"));
delete process.env.PI_WORKFLOW_FENCE;
const { default: register } = await import("./workflow-fence.ts");

let handler: any;
register({ on(name: string, fn: any) { if (name === "tool_call") handler = fn; } });

const F = "```";
const body = "const r = await agent({ agent: 'coder', task: 'x' });\nreturn r;";
const ctxFor = (text: string, id: string, extraCalls: any[] = []) => ({
  sessionManager: {
    getBranch: () => [
      { type: "message", message: { role: "user", content: "go" } },
      { type: "message", message: { role: "assistant", content: [
        { type: "text", text },
        { type: "toolCall", id, name: "subagent", arguments: { workflow: true } },
        ...extraCalls,
      ] } },
    ],
  },
});

let bad = 0;
let n = 0;
function check(name: string, ok: boolean, detail?: unknown) {
  n++;
  if (!ok) { bad++; console.log("FAIL    ", name, detail === undefined ? "" : JSON.stringify(detail)); }
}
function run(text: string, input: any, toolName = "subagent", id = `call-${n}`) {
  const event = { toolName, toolCallId: id, input };
  const r = handler(event, ctxFor(text, id));
  return { r, input: event.input };
}

// Plain js: pi-subagents finds 0 tagged blocks in this text; the call is pointed at a file holding the body.
{
  const { r, input } = run(`Running it.\n\n${F}js\n${body}\n${F}\n`, { workflow: true, args: { a: 1 } }, "subagent", "toolu|01:x");
  const path = input.workflow;
  check("plain js rewritten", r === undefined && typeof path === "string" && path.startsWith("/") && existsSync(path) && readFileSync(path, "utf8") === body, { r, path });
  check("plain js keeps args", input.args?.a === 1);
  check("plain js file under tmp", typeof path === "string" && path.startsWith(join(process.env.TMPDIR!, "hworks-workflows")) && !path.includes("|"), path);
}
{
  const { r, input } = run(`${F}javascript\n${body}\n${F}`, { workflow: "true" });
  check("javascript rewritten", r === undefined && typeof input.workflow === "string" && readFileSync(input.workflow, "utf8") === body, { r, input });
}
{
  const { r, input } = run(`~~~js\n${body}\n~~~`, { workflow: true });
  check("tilde js rewritten", r === undefined && typeof input.workflow === "string" && readFileSync(input.workflow, "utf8") === body, { r, input });
}
// Correctly tagged: untouched.
{
  const { r, input } = run(`${F}js workflow\n${body}\n${F}\n`, { workflow: true });
  check("tagged untouched", r === undefined && input.workflow === true, { r, input });
}
{
  const { r, input } = run(`${F}js workflow\n${body}\n${F}\n${F}js\n${body}\n${F}`, { workflow: true });
  check("tagged plus plain untouched", r === undefined && input.workflow === true, { r, input });
}
// Malformed tagged fences: blocked with the redirect, since pi-subagents rejects them without naming it.
{
  const { r, input } = run(`${F}js workflow\n${body}\n`, { workflow: true });
  check("unclosed tagged blocked", r?.block === true && input.workflow === true && /unclosed ```js workflow/.test(r?.reason ?? "") && (r?.reason ?? "").includes('workflow: "<absolute path>"'), r);
}
{
  const { r, input } = run(`${F}js workflow\n${body}\n${F}\n${F}js workflow\n${body}\n${F}`, { workflow: true });
  check("two tagged blocked", r?.block === true && input.workflow === true && /2 ```js workflow blocks/.test(r?.reason ?? ""), r);
}
{
  const { r, input } = run(`${F}js workflow\n${body}\n${F}\n${F}javascript workflow\n${body}\n`, { workflow: true });
  check("tagged plus unclosed tagged blocked", r?.block === true && input.workflow === true && /unclosed/.test(r?.reason ?? ""), r);
}
// No block: blocked, reason names the tag and the path form.
{
  const { r, input } = run("Run review-loop with these args.", { workflow: true });
  const reason = r?.reason ?? "";
  check("no block blocked", r?.block === true && input.workflow === true, r);
  check("no block reason", reason.includes("`js workflow`") && reason.includes('workflow: "<absolute path>"') && /\/workflows\/review-loop\.js/.test(reason), reason);
}
// Two plain blocks: blocked.
{
  const { r, input } = run(`${F}js\n${body}\n${F}\ntext\n${F}js\n${body}\n${F}`, { workflow: true });
  check("two plain blocked", r?.block === true && input.workflow === true && /2 untagged/.test(r?.reason ?? ""), r);
}
// Unclosed plain block: blocked.
{
  const { r } = run(`${F}js\n${body}\n`, { workflow: true });
  check("unclosed blocked", r?.block === true && /unclosed/.test(r?.reason ?? ""), r);
}
// A js block nested inside a longer fence is not counted.
{
  const { r, input } = run(`${F}\`markdown\n${F}js\n${body}\n${F}\n${F}\`\n`, { workflow: true });
  check("nested not counted", r?.block === true && /no ```js block/.test(r?.reason ?? "") && input.workflow === true, r);
}
{
  const { r, input } = run(`${F}\`markdown\n${F}js\nnested()\n${F}\n${F}\`\n${F}js\n${body}\n${F}`, { workflow: true });
  check("nested skipped, outer plain rewritten", r === undefined && typeof input.workflow === "string" && readFileSync(input.workflow, "utf8") === body, { r, input });
}
// String workflow and other tools: untouched.
{
  const { r, input } = run(`${F}js\n${body}\n${F}`, { workflow: "./wf.js" });
  check("string workflow untouched", r === undefined && input.workflow === "./wf.js", { r, input });
}
{
  const { r, input } = run(`${F}js\n${body}\n${F}`, { workflow: true }, "bash");
  check("other tool untouched", r === undefined && input.workflow === true, { r, input });
}
{
  const { r, input } = run(`${F}js\n${body}\n${F}`, { agent: "coder", task: "x" });
  check("absent workflow untouched", r === undefined && input.workflow === undefined, { r, input });
}
// Two workflow: true calls in one reply: left to pi-subagents.
{
  const id = "call-two";
  const event = { toolName: "subagent", toolCallId: id, input: { workflow: true } };
  const r = handler(event, ctxFor(`${F}js\n${body}\n${F}`, id, [{ type: "toolCall", id: "other", name: "subagent", arguments: { workflow: true } }]));
  check("two calls untouched", r === undefined && event.input.workflow === true, r);
}
// Handler errors leave the call unchanged.
{
  const event = { toolName: "subagent", toolCallId: "call-err", input: { workflow: true } };
  let r: any = "unset";
  try { r = handler(event, { sessionManager: { getBranch: () => { throw new Error("boom"); } } }); } catch (e) { r = e; }
  check("error path unchanged", r === undefined && event.input.workflow === true, r);
}
{
  const event = { toolName: "subagent", toolCallId: "call-missing", input: { workflow: true } };
  const r = handler(event, ctxFor(`${F}js\n${body}\n${F}`, "someone-else"));
  check("message not found unchanged", r === undefined && event.input.workflow === true, r);
}

console.log(bad ? `${bad} failures` : `all ${n} pass`);
process.exit(bad ? 1 : 0);
