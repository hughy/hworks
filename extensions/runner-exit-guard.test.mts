import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const { isRunnerArgv, guardExit, logPath } = await import("./runner-exit-guard.ts");

let bad = 0;
const check = (name: string, ok: boolean, detail?: unknown) => { if (!ok) { bad++; console.log("FAIL", name, detail ?? ""); } };

const node = "/usr/local/bin/node";
const root = "/x/node_modules/pi-subagents/src/runs/background";
check("node-host runner", isRunnerArgv([node, `${root}/subagent-runner-bootstrap.js`, "/tmp/cfg.json"]));
check("ts entry", isRunnerArgv([node, `${root}/subagent-runner-bootstrap.ts`]));
check("binary-host runner", isRunnerArgv([node, "/bin/pi", "--mode", "rpc", "--extension", `${root}/binary-bootstrap.js`]));
check("plain print session", !isRunnerArgv([node, "/bin/pi", "--mode", "json", "-p", "hi"]));
check("prompt names runner file", !isRunnerArgv([node, "/bin/pi", "-p", `${root}/subagent-runner-bootstrap.js`]));
check("prompt names binary bootstrap", !isRunnerArgv([node, "/bin/pi", "-p", "review", "/tmp/binary-bootstrap.js"]));
check("other extension", !isRunnerArgv([node, "/bin/pi", "--extension", "/tmp/other.js"]));
check("lookalike name", !isRunnerArgv([node, "/tmp/my-subagent-runner-bootstrap.js"]));

const dir = mkdtempSync(join(tmpdir(), "reg-"));
const log = join(dir, "sub", "guard.log");
const calls: unknown[] = [];
const proc = { pid: 42, exit: ((code?: unknown) => { calls.push(code); }) as any };
guardExit(proc, log);
proc.exit();
check("no-code exit ignored", calls.length === 0, calls);
check("ignored exit logged", existsSync(log) && /pid=42 ignored process\.exit\(\)/.test(readFileSync(log, "utf8")));
proc.exit(0);
proc.exit(1);
check("coded exits pass through", JSON.stringify(calls) === "[0,1]", calls);

check("log path override", logPath({ PI_RUNNER_EXIT_GUARD_LOG: "/a/b.log" }) === "/a/b.log");
check("log path agent dir", logPath({ PI_CODING_AGENT_DIR: "/agent" }) === "/agent/runner-exit-guard.log");

if (bad) { console.log(`${bad} failed`); process.exit(1); }
console.log("ok");
