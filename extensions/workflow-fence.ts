// Repairs `subagent({ workflow: true })` calls whose reply carries the script in a plain ```js fence.
// pi-subagents accepts only a fence tagged exactly `js workflow` / `javascript workflow`, and its
// "found 0" error does not name the tag, so agents retry blindly. With no tagged fence and exactly one
// untagged js fence, this writes the body to a temp file and points `workflow` at it. Any other
// untagged shape is blocked with a reason that names the tag and the path form.
// Pi appends the assistant message to the session on message_end, before it runs that message's tool
// calls, so the issuing message is on the branch when tool_call fires. PI_WORKFLOW_FENCE=0 disables it.

import { mkdirSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Same rules as pi-subagents src/extension/reply-workflow-script.js.
const WORKFLOW_FENCE = /^```(?:js|javascript) workflow[ \t]*$/;
const OPEN_FENCE = /^(`{3,}|~{3,})/;
const CLOSE_FENCE = /^(`{3,}|~{3,})[ \t]*$/;
const PLAIN_JS_INFO = /^(?:js|javascript)$/;

const REVIEW_LOOP = (() => {
  try {
    return join(dirname(dirname(realpathSync(fileURLToPath(import.meta.url)))), "workflows/review-loop.js");
  } catch {
    return "~/dev/hworks/workflows/review-loop.js";
  }
})();

export type Fences = { tagged: number; taggedUnclosed: boolean; plain: string[]; plainUnclosed: boolean };

export function scanFences(text: string): Fences {
  const lines = text.split("\n");
  const out: Fences = { tagged: 0, taggedUnclosed: false, plain: [], plainUnclosed: false };
  let fence: { marker: string; tagged: boolean; plain: boolean; start: number } | undefined;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].replace(/\r$/, "");
    if (!fence) {
      const open = OPEN_FENCE.exec(line);
      if (open) {
        const tagged = WORKFLOW_FENCE.test(line);
        fence = { marker: open[1], tagged, plain: !tagged && PLAIN_JS_INFO.test(line.slice(open[1].length).trim()), start: i + 1 };
      }
      continue;
    }
    const close = CLOSE_FENCE.exec(line);
    if (!close || close[1][0] !== fence.marker[0] || close[1].length < fence.marker.length) continue;
    if (fence.tagged) out.tagged++;
    else if (fence.plain) out.plain.push(lines.slice(fence.start, i).join("\n"));
    fence = undefined;
  }
  if (fence?.tagged) out.taggedUnclosed = true;
  if (fence?.plain) out.plainUnclosed = true;
  return out;
}

function isWorkflowTrue(value: unknown): boolean {
  return value === true || value === "true";
}

function issuingMessage(ctx: any, toolCallId: string): any[] | undefined {
  const branch = ctx?.sessionManager?.getBranch?.();
  if (!Array.isArray(branch)) return undefined;
  for (let i = branch.length - 1; i >= 0; i--) {
    const entry = branch[i];
    if (entry?.type !== "message") continue;
    const message = entry.message;
    if (message?.role !== "assistant" || !Array.isArray(message.content)) continue;
    if (message.content.some((b: any) => b?.type === "toolCall" && b.id === toolCallId)) return message.content;
  }
  return undefined;
}

function blockReason(found: string): string {
  return (
    `workflow-fence: workflow: true runs the one fenced block tagged \`\`\`js workflow (or \`\`\`javascript workflow) ` +
    `in the same reply as the call; this reply has ${found}. Either tag the fence \`js workflow\` in the reply that ` +
    `makes the call, or write the script to a file and pass workflow: "<absolute path>". To run an existing ` +
    `workflow file (for example ${REVIEW_LOOP}), pass its absolute path as workflow instead of workflow: true.`
  );
}

export type Decision = { action: "none" } | { action: "rewrite"; script: string } | { action: "block"; reason: string };

export function decide(content: any[]): Decision {
  const calls = content.filter((b) => b?.type === "toolCall" && b.name === "subagent" && isWorkflowTrue(b.arguments?.workflow));
  if (calls.length > 1) return { action: "none" };
  const text = content.flatMap((b) => (b?.type === "text" && typeof b.text === "string" ? [b.text] : [])).join("\n");
  const f = scanFences(text);
  // A tagged fence means the agent used the right form; pi-subagents' own errors cover its mistakes.
  if (f.tagged > 0 || f.taggedUnclosed) return { action: "none" };
  if (f.plainUnclosed) return { action: "block", reason: blockReason("an unclosed ```js block") };
  if (f.plain.length === 0) return { action: "block", reason: blockReason("no ```js block") };
  if (f.plain.length > 1) return { action: "block", reason: blockReason(`${f.plain.length} untagged \`\`\`js blocks`) };
  if (!f.plain[0].trim()) return { action: "block", reason: blockReason("an empty ```js block") };
  return { action: "rewrite", script: f.plain[0] };
}

export function handleToolCall(event: any, ctx: any): { block: true; reason: string } | undefined {
  try {
    if (event?.toolName !== "subagent" || !event.input || !isWorkflowTrue(event.input.workflow)) return;
    const content = issuingMessage(ctx, event.toolCallId);
    if (!content) return;
    const d = decide(content);
    if (d.action === "block") return { block: true, reason: d.reason };
    if (d.action !== "rewrite") return;
    const dir = join(tmpdir(), "hworks-workflows");
    mkdirSync(dir, { recursive: true });
    const file = join(dir, `${String(event.toolCallId).replace(/[^A-Za-z0-9_-]/g, "_")}.js`);
    writeFileSync(file, d.script);
    event.input.workflow = file;
  } catch {
    // A throwing tool_call handler blocks the tool; a failed repair must leave the call as it was.
  }
  return;
}

export default function (pi: any) {
  if (process.env.PI_WORKFLOW_FENCE === "0") return;
  pi.on("tool_call", handleToolCall);
}
