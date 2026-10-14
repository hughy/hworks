// Keeps extensions from killing a pi-subagents async runner. The runner hosts
// background child sessions in-process and ends each one with
// session_shutdown {reason: "quit"} in print mode. An extension that treats
// that as "the headless run is over" and calls process.exit() kills the runner
// while it still has gates, chain steps, and the run result to write. The run
// then fails with "Async runner process N exited with code 0 before writing a
// result".
//
// Inside a runner process only, this ignores process.exit() calls that pass no
// exit code. The runner's own exits always pass one (0 or 1), and neither
// pi-subagents nor pi calls process.exit() without one.
import { appendFileSync, existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, isAbsolute, join } from "node:path";

const GUARD = Symbol.for("hworks.runnerExitGuard");

const isEntry = (arg: string | undefined, name: string) =>
  typeof arg === "string" && new RegExp(`^${name}\\.[cm]?[jt]s$`).test(basename(arg));

const hasRunnerSibling = (bootstrap: string) =>
  [".js", ".mjs", ".cjs", ".ts", ".mts", ".cts"].some((ext) =>
    existsSync(join(dirname(bootstrap), `subagent-runner-bootstrap${ext}`)),
  );

// The exact arguments pi-subagents passes when the runner is a compiled pi binary.
const BINARY_HOST_TAIL = ["--no-extensions", "--no-skills", "--no-prompt-templates", "--no-session", "--mode", "rpc", "--extension"];

// pi-subagents starts the runner in one of two shapes:
//   node [node flags] .../subagent-runner-bootstrap.js cfg.json
//   pi --no-extensions --no-skills --no-prompt-templates --no-session --mode rpc --extension .../binary-bootstrap.js
// Node consumes its own flags, and jiti rewrites argv before it imports the
// runner, so the script is argv[1]. For the binary host, everything after the
// executable and its entry must be exactly those arguments, ending in an
// absolute binary-bootstrap that sits next to the runner bootstrap, so prompt
// text or option values cannot fake it. If
// pi-subagents changes this shape, the guard stops matching and runs fail with
// the original error instead of hiding other exits.
export function isRunnerArgv(argv: readonly string[], exists = hasRunnerSibling): boolean {
  if (isEntry(argv[1], "subagent-runner-bootstrap")) return true;
  if (argv.length !== BINARY_HOST_TAIL.length + 3) return false;
  if (!BINARY_HOST_TAIL.every((arg, i) => argv[i + 2] === arg)) return false;
  const bootstrap = argv[argv.length - 1];
  return isAbsolute(bootstrap) && isEntry(bootstrap, "binary-bootstrap") && exists(bootstrap);
}

export function logPath(env: NodeJS.ProcessEnv = process.env): string {
  return env.PI_RUNNER_EXIT_GUARD_LOG || join(env.PI_CODING_AGENT_DIR || join(homedir(), ".pi", "agent"), "runner-exit-guard.log");
}

type Exit = (code?: number | string | null) => never;
type Proc = { exit: Exit; pid: number };

export function guardExit(proc: Proc, log: string): void {
  const realExit = proc.exit.bind(proc) as Exit;
  proc.exit = ((code?: number | string | null) => {
    if (code !== undefined) return realExit(code);
    try {
      mkdirSync(dirname(log), { recursive: true });
      const caller = new Error().stack?.split("\n")[2]?.trim() ?? "unknown";
      appendFileSync(log, `${new Date().toISOString()} pid=${proc.pid} ignored process.exit() ${caller}\n`);
    } catch {}
    return undefined as never;
  }) as Exit;
}

export function install({
  argv = process.argv,
  env = process.env,
  proc = process as unknown as Proc,
  state = globalThis as Record<symbol, unknown>,
}: { argv?: readonly string[]; env?: NodeJS.ProcessEnv; proc?: Proc; state?: Record<symbol, unknown> } = {}): boolean {
  if (env.PI_RUNNER_EXIT_GUARD === "0") return false;
  // Child sessions reload extensions, so guard against wrapping twice.
  if (state[GUARD] || !isRunnerArgv(argv)) return false;
  state[GUARD] = true;
  guardExit(proc, logPath(env));
  return true;
}

export default function runnerExitGuard() {
  install();
}
