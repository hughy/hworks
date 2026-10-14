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

// pi-subagents starts the runner in one of three shapes:
//   node [--import x] [--experimental-strip-types] .../subagent-runner-bootstrap.js cfg.json
//   node [--import x] .../jiti/cli.mjs .../subagent-runner-bootstrap.ts cfg.json
//   pi --no-extensions ... --mode rpc --extension .../binary-bootstrap.js
// Node consumes its own flags, so the script is argv[1] (argv[2] under jiti).
// For the binary host, only a real --extension option counts: options before
// "--", pointing at an absolute binary-bootstrap that sits next to the runner
// bootstrap. Prompt text that names a file of the same name does not match.
export function isRunnerArgv(argv: readonly string[], exists = hasRunnerSibling): boolean {
  if (isEntry(argv[1], "subagent-runner-bootstrap")) return true;
  if (/jiti/.test(argv[1] ?? "") && isEntry(argv[2], "subagent-runner-bootstrap")) return true;
  for (let i = 2; i < argv.length - 1; i++) {
    if (argv[i] === "--") break;
    if (argv[i] !== "--extension" && argv[i] !== "-e") continue;
    const ext = argv[i + 1];
    if (isAbsolute(ext) && isEntry(ext, "binary-bootstrap") && exists(ext)) return true;
  }
  return false;
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
