import { mkdtempSync, mkdirSync, readFileSync, existsSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";
import { join } from "node:path";

const { isRunnerArgv, guardExit, logPath, install } = await import("./runner-exit-guard.ts");

let bad = 0;
const check = (name: string, ok: boolean, detail?: unknown) => { if (!ok) { bad++; console.log("FAIL", name, detail ?? ""); } };

const tmp = mkdtempSync(join(tmpdir(), "reg-"));
const bg = join(tmp, "pi-subagents", "src", "runs", "background");
mkdirSync(bg, { recursive: true });
writeFileSync(join(bg, "subagent-runner-bootstrap.js"), "");
writeFileSync(join(bg, "binary-bootstrap.js"), "");
const runner = join(bg, "subagent-runner-bootstrap.js");
const binary = join(bg, "binary-bootstrap.js");
const stray = join(tmp, "binary-bootstrap.js");
writeFileSync(stray, "");
const node = "/usr/local/bin/node";

const host = ["--no-extensions", "--no-skills", "--no-prompt-templates", "--no-session", "--mode", "rpc", "--extension"];
check("node-host runner", isRunnerArgv([node, runner, "/tmp/cfg.json"]));
check("strip-types runner", isRunnerArgv([node, join(bg, "subagent-runner-bootstrap.ts"), "/tmp/cfg.json"]));
check("binary-host runner", isRunnerArgv([node, "/bin/pi", ...host, binary]));
check("compiled binary-host runner", isRunnerArgv(["/bin/pi", "/$bunfs/root/pi", ...host, binary]));

check("plain print session", !isRunnerArgv([node, "/bin/pi", "--mode", "json", "-p", "hi"]));
check("prompt names runner file", !isRunnerArgv([node, "/bin/pi", "-p", runner]));
check("jiti in pi path", !isRunnerArgv([node, "/tmp/jiti-sandbox/pi", runner]));
check("bare --extension bootstrap", !isRunnerArgv([node, "/bin/pi", "--extension", binary]));
check("consumed option value", !isRunnerArgv([node, "/bin/pi", "--system-prompt", "--extension", binary]));
check("long argv ending in --extension bootstrap", !isRunnerArgv([node, "/bin/pi", "--mode", "json", "-p", "a", "b", "c", "--system-prompt", "--extension", binary]));
check("tail with one flag changed", !isRunnerArgv([node, "/bin/pi", ...host.map((a) => (a === "rpc" ? "json" : a)), binary]));
check("prompt after --", !isRunnerArgv([node, "/bin/pi", "-p", "--", "--extension", binary]));
writeFileSync(join(bg, "other.js"), "");
check("tail with another extension", !isRunnerArgv([node, "/bin/pi", ...host, join(bg, "other.js")]));
{
  const cwd = process.cwd();
  process.chdir(bg);
  check("relative bootstrap path", !isRunnerArgv([node, "/bin/pi", ...host, "binary-bootstrap.js"]));
  process.chdir(cwd);
}
check("bootstrap without runner sibling", !isRunnerArgv([node, "/bin/pi", ...host, stray]));
check("missing bootstrap", !isRunnerArgv([node, "/bin/pi", ...host, "/nowhere/binary-bootstrap.js"]));
check("lookalike name", !isRunnerArgv([node, join(bg, "my-subagent-runner-bootstrap.js")]));

const fakeProc = () => {
  const calls: unknown[] = [];
  const proc = { pid: 42, exit: ((code?: unknown) => { calls.push(code); }) as any };
  return { proc, calls };
};

const log = join(tmp, "sub", "guard.log");
{
  const { proc, calls } = fakeProc();
  guardExit(proc, log);
  proc.exit();
  check("no-code exit ignored", calls.length === 0, calls);
  check("ignored exit logged", existsSync(log) && /pid=42 ignored process\.exit\(\)/.test(readFileSync(log, "utf8")));
  proc.exit(0);
  proc.exit(1);
  check("coded exits pass through", JSON.stringify(calls) === "[0,1]", calls);
}

const env = { PI_RUNNER_EXIT_GUARD_LOG: log };
{
  const { proc, calls } = fakeProc();
  const original = proc.exit;
  const state = {};
  check("install in runner", install({ argv: [node, runner], env, proc, state }) === true);
  check("install wraps exit", proc.exit !== original);
  const wrapped = proc.exit;
  check("second install skipped", install({ argv: [node, runner], env, proc, state }) === false && proc.exit === wrapped);
  proc.exit();
  check("installed guard ignores no-code exit", calls.length === 0, calls);
}
{
  const { proc } = fakeProc();
  const original = proc.exit;
  check("non-runner untouched", install({ argv: [node, "/bin/pi", "-p", "hi"], env, proc, state: {} }) === false && proc.exit === original);
}
{
  const { proc } = fakeProc();
  const original = proc.exit;
  check("off switch", install({ argv: [node, runner], env: { ...env, PI_RUNNER_EXIT_GUARD: "0" }, proc, state: {} }) === false && proc.exit === original);
}

// The default export reads the real process, so run it in a child whose
// entry script is named like the runner (or not) and see whether exit() kills it.
const ext = new URL("./runner-exit-guard.ts", import.meta.url).href;
const script = (name: string) => {
  const file = join(tmp, name);
  writeFileSync(file, `const { default: guard } = await import(${JSON.stringify(ext)});\nguard();\nguard();\nprocess.exit();\nconsole.log("alive");\nprocess.exit(3);\n`);
  return file;
};
const run = (file: string, extra: Record<string, string> = {}) =>
  spawnSync(process.execPath, ["--experimental-strip-types", "--no-warnings", file], { env: { ...process.env, PI_RUNNER_EXIT_GUARD_LOG: join(tmp, "child.log"), ...extra }, encoding: "utf8" });
{
  const r = run(script("subagent-runner-bootstrap.mjs"));
  check("default export guards runner", r.stdout.trim() === "alive" && r.status === 3, r);
  const lines = readFileSync(join(tmp, "child.log"), "utf8").trim().split("\n");
  check("default export wraps once", lines.length === 1, lines);
  const off = run(join(tmp, "subagent-runner-bootstrap.mjs"), { PI_RUNNER_EXIT_GUARD: "0" });
  check("default export off switch", off.stdout === "" && off.status === 0, off);
  const plain = run(script("not-a-runner.mjs"));
  check("default export ignores other processes", plain.stdout === "" && plain.status === 0, plain);
}

check("log path override", logPath({ PI_RUNNER_EXIT_GUARD_LOG: "/a/b.log" }) === "/a/b.log");
check("log path agent dir", logPath({ PI_CODING_AGENT_DIR: "/agent" }) === "/agent/runner-exit-guard.log");

if (bad) { console.log(`${bad} failed`); process.exit(1); }
console.log("ok");
