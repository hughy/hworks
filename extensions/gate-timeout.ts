// Keeps gate and test runs from dying on the bash tool's timeout. The harness kills a foreground bash call at
// its `timeout` (300 s when none is passed, capped at 1800 s), and agents often pass 10-120 s, so a full test
// run or gate ends as "Command timed out" and is rerun. For a bash call whose command runs a gate or test
// (go test, pytest, make check, mutate.py, scripts/check.sh, ...), this sets `timeout` to the cap. Handlers
// mutate the same input in load order, and the harness only lowers values above the cap or fills a missing
// one, so the result is the same whichever extension runs first. Long commands that are not gates keep the
// global rule: start them with a background process. PI_GATE_TIMEOUT=0 disables it.

import { stripData } from "./autonomy.ts";

export const MAX_TIMEOUT_S = 1800;

// Leading words that wrap a command without changing what runs.
const WRAPPER = /^(?:\w+=\S*|env|time|nice|nohup|exec|command|caffeinate|do|then|else|if|while|until)$/;
const PY = String.raw`(?:(?:\S*/)?python[\d.]*\s+(?:-\S+\s+)*)`;

const GATES: Array<[string, RegExp]> = [
  ["go test/vet/build", /^go\s+(?:test|vet|build)\b/],
  ["python -m pytest/unittest", new RegExp(String.raw`^${PY}-m\s+(?:pytest|unittest)\b`)],
  ["pytest", /^(?:\S*\/)?pytest\b/],
  ["mutate.py", new RegExp(String.raw`^${PY}?\S*mutate\.py\b`)],
  ["make gate target", /^make\b.*?\s(?:[\w.]*[-_:/])?(?:tests?|check|lint|gate|ci|e2e|verify)(?:[-_:][\w.:-]*)?(?=\s|$)/],
  ["golangci-lint run", /^(?:\S*\/)?golangci-lint\s+run\b/],
  ["package-manager test/build", /^(?:npm|pnpm|yarn|bun)(?:\s+--?[\w-]+(?:[=\s](?!-)\S+)?)*\s+(?:run\s+)?(?:test|check|lint|build|e2e)(?:[-:]\S*)?(?=\s|$)/],
  ["jest/vitest/playwright", /^(?:npx\s+|pnpm\s+exec\s+)?(?:jest|vitest|playwright\s+test)\b/],
  ["cargo test/build", /^cargo\s+(?:test|build|clippy|nextest)\b/],
  ["forge test/build", /^forge\s+(?:test|build|coverage)\b/],
  ["node --test", /^node\s+(?:--\S+\s+)*--test\b/],
  ["node test file", /^node\s+(?:--\S+\s+)*\S*\.test\.[cm]?[jt]s\b/],
  ["gate script", new RegExp(String.raw`^(?:(?:ba|z)?sh\s+|${PY})?\S*\b(?:check|gate|smoke|e2e|test)[\w-]*\.sh\b`)],
  ["gate script", new RegExp(String.raw`^${PY}?\S*(?:gate|smoke|e2e)[\w-]*\.py\b`)],
];

function head(segment: string): string {
  const toks = segment.replace(/^[\s({!]+/, "").split(/\s+/);
  for (;;) {
    if (toks.length && WRAPPER.test(toks[0])) toks.shift();
    else if (toks[0] === "timeout") {
      toks.shift();
      while (toks.length && /^(?:-\S+|[\d.]+[smhd]?)$/.test(toks[0])) toks.shift();
    } else break;
  }
  return toks.join(" ");
}

// Returns the name of the gate the command runs, or null.
export function gateCommand(command: string): string | null {
  for (const segment of stripData(command).split(/[;&|\n]+|\$\(|`/)) {
    const h = head(segment);
    for (const [name, re] of GATES) if (re.test(h)) return name;
  }
  return null;
}

export function handleToolCall(event: any): void {
  try {
    if (event?.toolName !== "bash" || !event.input) return;
    if (gateCommand(String(event.input.command ?? ""))) event.input.timeout = MAX_TIMEOUT_S;
  } catch {
    // A throwing tool_call handler blocks the tool; leave the call as it was.
  }
}

export default function (pi: any) {
  if (process.env.PI_GATE_TIMEOUT === "0") return;
  pi.on("tool_call", handleToolCall);
}
