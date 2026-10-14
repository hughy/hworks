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
import { appendFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join } from "node:path";

const GUARD = Symbol.for("hworks.runnerExitGuard");

const isEntry = (arg: string | undefined, name: string) =>
  typeof arg === "string" && new RegExp(`^${name}\\.[cm]?[jt]s$`).test(basename(arg));

// The runner starts as `node .../subagent-runner-bootstrap.js` or, with a
// binary host, as `pi ... --extension .../binary-bootstrap.js`. Only those
// launch positions count, so prompt text that mentions the files does not.
export function isRunnerArgv(argv: readonly string[]): boolean {
  if (isEntry(argv[1], "subagent-runner-bootstrap")) return true;
  const i = argv.indexOf("--extension");
  return i >= 0 && isEntry(argv[i + 1], "binary-bootstrap");
}

export function logPath(env: NodeJS.ProcessEnv = process.env): string {
  return env.PI_RUNNER_EXIT_GUARD_LOG || join(env.PI_CODING_AGENT_DIR || join(homedir(), ".pi", "agent"), "runner-exit-guard.log");
}

type Exit = (code?: number | string | null) => never;

export function guardExit(proc: { exit: Exit; pid: number }, log: string): void {
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

export default function runnerExitGuard() {
  if (process.env.PI_RUNNER_EXIT_GUARD === "0") return;
  const state = globalThis as Record<symbol, unknown>;
  // Child sessions reload extensions, so guard against wrapping twice.
  if (state[GUARD] || !isRunnerArgv(process.argv)) return;
  state[GUARD] = true;
  guardExit(process as unknown as { exit: Exit; pid: number }, logPath());
}
