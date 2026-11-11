import { execFileSync, spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, join, relative, sep } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const workflows = ["review-loop", "review-fanout"];
const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const allowedSchemaKeys = new Set(["type", "enum", "description", "properties", "required", "additionalProperties", "items"]);
const git = (cwd, ...argv) => execFileSync("git", argv, { cwd, encoding: "utf8" }).trim();
const head = cwd => git(cwd, "rev-parse", "--verify", "HEAD");
const branch = cwd => git(cwd, "symbolic-ref", "HEAD");
const dirty = cwd => Boolean(git(cwd, "status", "--porcelain", "--untracked-files=all"));
const root = fileURLToPath(new URL("..", import.meta.url)).replace(/\/$/, "");

function inside(parent, child) {
  const path = relative(realpathSync(parent), realpathSync(child));
  return path !== ".." && !path.startsWith(".." + sep) && !isAbsolute(path);
}

// Codex structured output requires closed objects with all properties declared required.
// A nullable field represents a pi optional property; remove that null after validation.
function strictSchema(schema) {
  if (!object(schema) || Object.keys(schema).some(key => !allowedSchemaKeys.has(key))) {
    throw new Error("unsupported Codex output schema keyword");
  }
  if (schema.type === "object") {
    if (!object(schema.properties) || schema.additionalProperties === true) throw new Error("expected declared object properties");
    const properties = Object.fromEntries(Object.entries(schema.properties).map(([key, spec]) => {
      const field = strictSchema(spec);
      return [key, schema.required?.includes(key) ? field : { anyOf: [field, { type: "null" }] }];
    }));
    return { ...schema, properties, required: Object.keys(properties), additionalProperties: false };
  }
  if (schema.type === "array") return { ...schema, items: strictSchema(schema.items) };
  if (!["string", "integer", "number", "boolean", "null", undefined].includes(schema.type) ||
      (schema.type === undefined && !Array.isArray(schema.enum))) throw new Error("unsupported Codex output schema type");
  return schema.type === undefined ? { ...schema, type: "string" } : schema;
}

function validate(value, schema, path = "output") {
  function expect(ok) {
    if (!ok) throw new Error("Codex result does not match schema at " + path);
  }
  if (schema.enum) expect(schema.enum.includes(value));
  switch (schema.type) {
    case "object":
      expect(object(value) && Object.keys(value).every(key => Object.hasOwn(schema.properties, key)));
      return Object.fromEntries(Object.entries(schema.properties).flatMap(([key, spec]) => {
        const required = schema.required?.includes(key);
        if (!required && (!Object.hasOwn(value, key) || value[key] === null)) return [];
        expect(Object.hasOwn(value, key));
        return [[key, validate(value[key], spec, path + "." + key)]];
      }));
    case "array":
      expect(Array.isArray(value));
      return value.map((item, i) => validate(item, schema.items, path + "[" + i + "]"));
    case "null": expect(value === null); break;
    case "integer": expect(Number.isSafeInteger(value)); break;
    case "number": expect(Number.isFinite(value)); break;
    case "string":
    case "boolean": expect(typeof value === schema.type); break;
  }
  return value;
}

const children = new Map();
let interrupted;
let cleanupUncertain = false;
function signalGroup(pid, signal) {
  try {
    process.kill(-pid, signal);
    return true;
  } catch (error) {
    if (error.code !== "ESRCH") throw error;
    return false;
  }
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    interrupted = signal;
    for (const stop of children.values()) stop();
  });
}

async function run(command, argv, { cwd, timeout, env = process.env, input }) {
  if (interrupted) throw new Error("interrupted by " + interrupted);
  const child = spawn(command, argv, { cwd, env, detached: true, stdio: [input ? "pipe" : "ignore", process.stderr, process.stderr] });
  let timedOut = false;
  let killTimer;
  let forced = false;
  function stop() {
    if (!child.pid || killTimer) return;
    signalGroup(child.pid, "SIGTERM");
    killTimer = setTimeout(() => { forced = signalGroup(child.pid, "SIGKILL"); }, 15000);
  }
  if (child.pid) children.set(child.pid, stop);
  const timer = setTimeout(() => { timedOut = true; stop(); }, timeout);
  try {
    const result = await new Promise((resolve, reject) => {
      child.once("error", reject);
      child.once("close", (code, signal) => resolve({ code, signal, timedOut }));
      if (input) {
        child.stdin.on("error", () => stop());
        child.stdin.end(input);
      }
    });
    if (child.pid && signalGroup(child.pid, 0)) {
      stop();
      const deadline = Date.now() + 16000;
      while (signalGroup(child.pid, 0)) {
        if (Date.now() >= deadline) {
          cleanupUncertain = true;
          throw new Error("child process group " + child.pid + " did not exit");
        }
        await delay(100);
      }
    }
    if (forced || result.signal === "SIGKILL") {
      cleanupUncertain = true;
      throw new Error("forced child termination; detached descendants may still be active");
    }
    if (interrupted) throw new Error("interrupted by " + interrupted);
    return result;
  } finally {
    clearTimeout(timer);
    clearTimeout(killTimer);
    if (child.pid) children.delete(child.pid);
  }
}

function description(result) {
  return result.signal || "exit " + result.code;
}

function taskFor(item, writer, pinnedHead) {
  const rolePath = new URL("../agents/" + item.agent + ".md", import.meta.url);
  const role = readFileSync(rolePath, "utf8")
    .replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, "")
    .replaceAll("~/dev/hworks", root);
  const rules = writer
    ? "The host owns staging and commits. Leave only changes intended for the commit. Start summary with a Conventional Commit title, or use summary to report a blocker."
    : "The sandbox is read-only. Use source and read-only commands for evidence. Disclose any check that would need writes instead of claiming it ran.";
  const pin = pinnedHead ? "Review commit " + pinnedHead + ". Use that SHA in Git commands." : "";
  return ["Apply the role and task subject to these Codex runtime rules: " + rules + " " + pin, role, item.task].join("\n\n");
}

async function runWorkflow(name, args) {
  if (!object(args)) throw new Error("workflow args must be a JSON object");
  const timeout = args.childTimeoutMs ?? 1800000;
  if (!Number.isSafeInteger(timeout) || timeout < 1 || timeout > 2147483647) {
    throw new Error("childTimeoutMs must be a positive timeout in milliseconds");
  }
  const loop = name === "review-loop";
  const cwd = args.cwd || process.cwd();
  const targets = loop ? [cwd] : (Array.isArray(args.targets) ? args.targets.map(target => target?.cwd) : []);
  if (args.taskDir && targets.some(dir => typeof dir === "string" && dir && inside(dir, args.taskDir))) {
    throw new Error("taskDir must be outside each target checkout");
  }
  let initialBranch, currentHead;
  if (loop) {
    if (realpathSync(cwd) !== realpathSync(git(cwd, "rev-parse", "--show-toplevel")) || dirty(cwd)) {
      throw new Error("review-loop requires a clean worktree root");
    }
    initialBranch = branch(cwd);
    currentHead = head(cwd);
  }
  const temp = mkdtempSync(join(tmpdir(), "hworks-codex-"));
  const gateEnv = { ...process.env };
  delete gateEnv.CODEX_API_KEY;
  delete gateEnv.OPENAI_API_KEY;

  async function worker(item) {
    const runId = randomUUID();
    const fail = (error, timedOut = false) => ({ runId, ok: false, error, timedOut });
    const dir = item.cwd || cwd;
    const writer = Boolean(item.acceptance);
    const pinnedHead = loop && !writer ? currentHead : item.pinnedHead;
    if (!(writer ? item.agent === "coder" : ["reviewer", "explorer", "synthesizer"].includes(item.agent))) {
      return fail("unknown Codex workflow role: " + item.agent);
    }
    const schemaFile = join(temp, runId + "-schema.json");
    const outputFile = join(temp, runId + "-output.json");
    const schema = item.outputSchema.type === "object" ? item.outputSchema : {
      type: "object", properties: { result: item.outputSchema }, required: ["result"],
    };
    writeFileSync(schemaFile, JSON.stringify(strictSchema(schema)));
    const cli = ["-a", "never", "exec", "-s", writer ? "workspace-write" : "read-only",
      "--skip-git-repo-check", "--output-schema", schemaFile, "-o", outputFile,
      "-c", 'shell_environment_policy.exclude=["CODEX_API_KEY","OPENAI_API_KEY"]'];
    const model = item.model || process.env.HWORKS_CODEX_MODEL;
    if (model) cli.push("-m", model);
    if (writer && args.reviewers === 0) cli.push("-c", 'model_reasoning_effort="low"');
    if (loop && (head(dir) !== currentHead || branch(dir) !== initialBranch || (!writer && dirty(dir)))) {
      throw new Error("worktree changed outside the Codex workflow");
    }
    if (pinnedHead && (head(dir) !== pinnedHead || dirty(dir))) {
      return fail("pinned review requires a clean checkout of " + pinnedHead);
    }
    const result = await run(process.env.HWORKS_CODEX || "codex", [...cli, "-"], {
      cwd: dir, timeout, input: taskFor(item, writer, pinnedHead),
    });
    if (result.timedOut) return fail("Subagent timed out after " + timeout + "ms.", true);
    if (result.code !== 0) return fail("codex exec failed (" + description(result) + ")");
    let structuredOutput;
    try {
      const output = validate(JSON.parse(readFileSync(outputFile, "utf8")), schema);
      structuredOutput = schema === item.outputSchema ? output : output.result;
    } catch (error) {
      return fail(error.message);
    }
    if (item.output) writeFileSync(item.output, JSON.stringify(structuredOutput, null, 2) + "\n");
    if (writer && structuredOutput.status === "done") {
      if (head(dir) !== currentHead || branch(dir) !== initialBranch || structuredOutput.head !== currentHead) {
        throw new Error("worktree HEAD changed during the coder run");
      }
      if (dirty(dir)) {
        const title = structuredOutput.summary.trim().split(/\r?\n/)[0];
        const message = /^(feat|fix|build|chore|ci|docs|style|refactor|perf|test)!?: .+/.test(title)
          ? title : "fix: " + (title || "apply review workflow changes");
        const added = await run("git", ["add", "--all"], { cwd: dir, timeout, env: gateEnv });
        if (added.code !== 0 || added.timedOut) throw new Error("could not stage coder changes");
        const committed = await run("git", ["commit", "-m", message.slice(0, 80)], { cwd: dir, timeout, env: gateEnv });
        if (committed.code !== 0 || committed.timedOut) throw new Error("could not commit coder changes");
      }
      currentHead = head(dir);
      structuredOutput.head = currentHead;
      const [gate] = item.acceptance.verify;
      const checked = await run("sh", ["-c", gate.command], { cwd: dir, timeout: gate.timeoutMs, env: gateEnv });
      if (head(dir) !== currentHead || branch(dir) !== initialBranch || dirty(dir)) {
        throw new Error("host gate changed the reviewed worktree");
      }
      if (checked.timedOut || checked.code !== 0) {
        const why = checked.timedOut ? "timed out" : description(checked);
        return fail("Acceptance verification 'gate' failed: " + why + ". See host gate log.");
      }
    }
    if (pinnedHead && (head(dir) !== pinnedHead || (loop && branch(dir) !== initialBranch) || dirty(dir))) {
      throw new Error("worktree changed during Codex review");
    }
    return { runId, ok: true, structuredOutput };
  }

  const runs = {
    async all(items) {
      const results = await Promise.allSettled(items.map(worker));
      return results.map(result => {
        if (result.status === "rejected") throw result.reason;
        return result.value;
      });
    },
  };
  try {
    const source = readFileSync(new URL("../workflows/" + name + ".js", import.meta.url), "utf8");
    const workflow = new AsyncFunction("args", "runs", source);
    return await workflow({ ...args, runtime: "codex" }, runs);
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
}

try {
  const [name, argsFile, extra] = process.argv.slice(2);
  if (!workflows.includes(name) || !argsFile || extra) {
    throw new Error("usage: node scripts/codex-workflow.mjs <review-loop|review-fanout> <args.json>");
  }
  const value = await runWorkflow(name, JSON.parse(readFileSync(argsFile, "utf8")));
  if (interrupted) throw new Error("interrupted by " + interrupted);
  console.log(JSON.stringify(value));
} catch (error) {
  console.error("codex-workflow: " + error.message);
  process.exitCode = cleanupUncertain ? 125 : interrupted === "SIGINT" ? 130 : interrupted ? 143 : 1;
}
