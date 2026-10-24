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

const MAKE_TARGET = /^(?:[\w.]*[-_:/])?(?:tests?|check|lint|gate|ci|e2e|verify)(?:[-_:][\w.:-]*)?$/;
// make options whose value is the next word, so a makefile or directory named `test` is not a target.
const MAKE_OPTION_ARG = new Set(["-C", "-f", "-I", "-o", "-W", "--directory", "--file", "--makefile", "--include-dir",
  "--old-file", "--assume-old", "--new-file", "--assume-new", "--what-if"]);

// In `-sfCI` the first value-taking letter (`f`) takes the rest of the word (`CI`) as its value; only a
// value-taking letter at the end of the word takes the next word.
function shortOptionTakesNext(t: string): boolean {
  if (!/^-[a-zA-Z]+$/.test(t)) return false;
  const k = t.slice(1).search(/[CfIoW]/);
  return k === t.length - 2;
}

function makeRunsGate(h: string): boolean {
  const toks = h.split(/\s+/);
  if (toks[0] !== "make") return false;
  for (let i = 1; i < toks.length; i++) {
    const t = toks[i];
    if (MAKE_OPTION_ARG.has(t) || shortOptionTakesNext(t)) i++;
    else if (!t.startsWith("-") && !t.includes("=") && MAKE_TARGET.test(t)) return true;
  }
  return false;
}

// Node options before the script; `--check`/`-c` there only parses the file. Arguments after it go to the test.
const NODE_OPTION_ARG = new Set(["-r", "--require", "--import", "--loader", "--experimental-loader", "-e", "--eval",
  "-p", "--print", "--env-file", "--conditions", "-C", "--input-type", "--title", "--stack-size"]);

function nodeRunsTestFile(h: string): boolean {
  const toks = h.split(/\s+/);
  if (toks[0] !== "node") return false;
  for (let i = 1; i < toks.length; i++) {
    const t = toks[i];
    if (t === "--check" || t === "-c") return false;
    if (NODE_OPTION_ARG.has(t)) i++;
    else if (!t.startsWith("-")) return /\.test\.[cm]?[jt]s$/.test(t);
  }
  return false;
}

const GATES: Array<[string, { test(h: string): boolean }]> = [
  ["go test/vet/build", /^go\s+(?:test|vet|build)\b/],
  ["python -m pytest/unittest", new RegExp(String.raw`^${PY}-m\s+(?:pytest|unittest)\b`)],
  ["pytest", /^(?:\S*\/)?pytest\b/],
  ["mutate.py", new RegExp(String.raw`^${PY}?\S*mutate\.py\b`)],
  ["make gate target", { test: makeRunsGate }],
  ["golangci-lint run", /^(?:\S*\/)?golangci-lint\s+run\b/],
  ["package-manager test/build", /^(?:npm|pnpm|yarn|bun)(?:\s+--?[\w-]+(?:[=\s](?!-)\S+)?)*\s+(?:run\s+)?(?:test|check|lint|build|e2e)(?:[-:]\S*)?(?=\s|$)/],
  ["jest/vitest/playwright", /^(?:npx\s+|pnpm\s+exec\s+)?(?:jest|vitest|playwright\s+test)\b/],
  ["cargo test/build", /^cargo\s+(?:test|build|clippy|nextest)\b/],
  ["forge test/build", /^forge\s+(?:test|build|coverage)\b/],
  ["node --test", /^node\s+(?:--\S+\s+)*--test\b/],
  ["node test file", { test: nodeRunsTestFile }],
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

// stripData drops a heredoc opener's whole line with the body, which hides `python3 - <<'PY' | mutate.py -`.
// Classify the rest of each opener line too; a wrong guess here only raises a timeout.
function heredocOpenerRests(command: string): string[] {
  return [...command.matchAll(/<<-?\s*(['"]?)\w+\1([^\n]*)/g)].map((m) => stripData(m[2]));
}

// Returns the name of the gate the command runs, or null.
export function gateCommand(command: string): string | null {
  const code = [stripData(command), ...heredocOpenerRests(command)].join("\n");
  for (const segment of code.split(/[;&|\n]+|\$\(|`/)) {
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
