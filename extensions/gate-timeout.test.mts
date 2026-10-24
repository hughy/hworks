delete process.env.PI_GATE_TIMEOUT;
const { default: register, gateCommand, MAX_TIMEOUT_S } = await import("./gate-timeout.ts");

let handler: any;
register({ on(name: string, fn: any) { if (name === "tool_call") handler = fn; } });

let bad = 0;
let n = 0;
function check(name: string, ok: boolean, detail?: unknown) {
  n++;
  if (!ok) { bad++; console.log("FAIL    ", name, detail === undefined ? "" : JSON.stringify(detail)); }
}

// Each command below timed out in foreground bash in a past session; the comment gives the limit it hit.
const gates: Array<[string, string]> = [
  ["go test e2e (300 s default)", "go test ./e2e/fortgrpc ./e2e/suite-1 ./e2e/fx-execution"],
  ["go test to a log (60 s)",
    "go test ./internal/execution/validation ./internal/server ./internal/appconfig ./cmd/server > /tmp/chain6177-current.log 2>&1; tail -28 /tmp/chain6177-current.log"],
  ["unittest discover (300 s)", "PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -v; /bin/sh -n scripts/install-linter.sh; git diff --check"],
  ["go build && go vet (300 s)", "grep -n 'swapservice' internal/sepoliaswap/*.go; go build ./... && go vet ./internal/sepoliaswap/ ./cmd/... 2>&1 | tail -20"],
  ["mutate.py with env prefix (300 s)", "O=$(mktemp -d); export GOMAXPROCS=4; python3 /Users/hughy/dev/hworks/scripts/mutate.py --out $O/out $D/mutations.json 2>&1 | tail -40"],
  ["mutate.py fed by a heredoc on the same line (60 s)",
    "python3 - <<'PY' | ~/dev/hworks/scripts/mutate.py --json --keep -\nimport json\nprint(json.dumps({'mutants': []}))\nPY"],
  ["cargo build in a subshell with timeout (450 s)",
    "cd /tmp/w/pr-98; (timeout 400 cargo build -q --offline --locked -p dr-quote 2>&1 | tail -5); ls target/debug/dr-quote"],
  ["playwright after a wait loop (280 s)",
    "cd apps/web && timeout 280 npx playwright test agent-faults 2>&1 | head -20"],
  ["forge build (600 s)", "(cd lib/smart-wallet && git checkout -q a8c6456) ; forge build 2>&1 | tail -15; git status --short"],
  ["repo check script", "bash scripts/check.sh"],
  ["make lint target", "make lint-go"],
  ["pytest", "uvx pytest -q || pytest -q tests/"],
  ["node --test", "node --test workflows/*.test.js"],
  ["make -C dir target", "make -C services/api test"],
  ["make ci target", "make ci-test-race"],
  ["npm --prefix", "npm --prefix apps/web test"],
  ["go test in a for loop", "for pkg in a b; do go test \"$pkg\"; done"],
  ["node test file", "node --experimental-strip-types extensions/autonomy.test.mts"],
];
for (const [name, cmd] of gates) check(`gate: ${name}`, gateCommand(cmd) !== null, cmd);

// Past commands that name a gate only as data: process listings, searches, reads, commit messages, heredoc bodies.
const notGates: Array<[string, string]> = [
  ["ps | grep for lint", "ps -axo pid,ppid,etime,command | grep -E '[g]olangci-lint|[m]ake lint-go' | head -20; golangci-lint cache status"],
  ["rg for make targets", "rg -n 'ci-test-race|lint-go' Makefile"],
  ["reading mutate.py", "head -105 /Users/hughy/dev/hworks/scripts/mutate.py; sed -n '1,200p' scripts/check.sh"],
  ["commit message", "git commit -m \"fix: make go test pass under -race\""],
  ["heredoc body", "cat > notes.md <<'EOF'\ngo test ./...\nmake test\nEOF"],
  ["task-dir.sh", "~/dev/hworks/scripts/task-dir.sh chain-6181"],
  ["review-pre-read", "python3 /Users/hughy/dev/hworks/scripts/review-pre-read.py origin/master HEAD"],
  ["go run", "go run /tmp/decode_check.go"],
  ["make target containing ci", "make special && make specify && make facilities"],
  ["npm install", "npm install"],
  ["make makefile named test", "make -C services/api -f test clean"],
  ["node --check on a test file", "node --check extensions/autonomy.test.mts"],
];
for (const [name, cmd] of notGates) check(`not a gate: ${name}`, gateCommand(cmd) === null, { cmd, got: gateCommand(cmd) });

function call(input: any, toolName = "bash") {
  const event = { toolName, input };
  const r = handler(event);
  return { r, input: event.input };
}
{
  const { r, input } = call({ command: "go test ./e2e/fortgrpc" });
  check("no timeout passed: raised to the cap", r === undefined && input.timeout === MAX_TIMEOUT_S, input);
}
{
  const { input } = call({ command: "go test ./internal/server > /tmp/x.log 2>&1; tail -28 /tmp/x.log", timeout: 60 });
  check("short timeout passed: raised to the cap", input.timeout === MAX_TIMEOUT_S, input);
}
{
  const { input } = call({ command: "go test ./...", timeout: 300 });
  check("harness default already injected: raised to the cap", input.timeout === MAX_TIMEOUT_S, input);
}
{
  const { input } = call({ command: "git status --short", timeout: 10 });
  check("non-gate keeps its timeout", input.timeout === 10, input);
}
{
  const { input } = call({ command: "ls" });
  check("non-gate gets no timeout", !("timeout" in input), input);
}
{
  const { input } = call({ command: "go test ./..." }, "bg_process");
  check("other tools untouched", !("timeout" in input), input);
}
{
  let threw = false;
  try { handler({ toolName: "bash", input: { command: { toString() { throw new Error("x"); } } } }); } catch { threw = true; }
  check("handler never throws", !threw);
}
{
  process.env.PI_GATE_TIMEOUT = "0";
  let registered = false;
  const mod = await import("./gate-timeout.ts?off");
  mod.default({ on() { registered = true; } });
  check("PI_GATE_TIMEOUT=0 registers nothing", !registered);
}

if (bad) {
  console.log(`${bad} of ${n} checks failed`);
  process.exit(1);
}
console.log(`all ${n} checks pass`);
