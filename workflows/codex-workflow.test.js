const { spawn, spawnSync, execFileSync } = require("node:child_process");
const { once } = require("node:events");
const { chmodSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const { setTimeout: delay } = require("node:timers/promises");
const { test } = require("node:test");
const assert = require("node:assert/strict");

const runner = join(__dirname, "../scripts/codex-workflow.mjs");

function fixture(t, mode = "clean") {
  const dir = mkdtempSync(join(tmpdir(), "codex-workflow-test-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const cwd = join(dir, "repo");
  mkdirSync(cwd);
  const git = (...argv) => execFileSync("git", argv, { cwd, encoding: "utf8" }).trim();
  git("init", "-q", "-b", "test");
  git("config", "user.name", "Workflow Test");
  git("config", "user.email", "workflow@example.com");
  git("commit", "-qm", "initial", "--allow-empty");
  const base = git("rev-parse", "HEAD");
  const brief = join(dir, "brief.md");
  writeFileSync(brief, "Change the sample.");
  const fake = join(dir, "codex");
  writeFileSync(fake, `#!${process.execPath}
const fs = require("node:fs");
const git = (...args) => require("node:child_process").execFileSync("git", args, { encoding: "utf8" }).trim();
const argv = process.argv.slice(2);
const write = argv.includes("workspace-write");
const mode = process.env.TEST_CODEX_MODE;
const fixture = process.env.TEST_CODEX_DIR;
const schema = JSON.parse(fs.readFileSync(argv[argv.indexOf("--output-schema") + 1], "utf8"));
const output = argv[argv.indexOf("-o") + 1];
const prompt = fs.readFileSync(0, "utf8");
if (argv[0] !== "-a" || argv[1] !== "never" || schema.additionalProperties !== false) process.exit(2);
if (!write && !argv.includes("read-only")) process.exit(2);
fs.appendFileSync(fixture + "/calls", (write ? "write" : "read") + "\\n");
const head = git("rev-parse", "HEAD");
if (mode === "cancel") {
  process.on("SIGTERM", () => {
    fs.writeFileSync(fixture + "/cancelled", "yes");
    process.exit(0);
  });
  console.error("fake ready");
  setInterval(() => {}, 100);
} else if (write) {
  fs.writeFileSync("sample", prompt.includes("This is fix round 2.") ? "fixed" : "changed");
  fs.writeFileSync(output, JSON.stringify({ status: "done", head, summary: "fix: change sample", risks: null }));
} else {
  if (!prompt.includes("Review commit " + head)) process.exit(3);
  if (mode === "stale") git("commit", "-qm", "external move", "--allow-empty");
  const findings = mode === "fix" && fs.readFileSync("sample", "utf8") !== "fixed"
    ? [{ severity: "blocking", file: "sample", line: 1, claim: "needs fix", evidence: "read sample", origin: "new" }] : [];
  const value = schema.properties.verdict
    ? { verdict: findings.length ? "blocked" : "ok", findings, checked: [{ claim: "sample checked", evidence: "read sample:1" }], addedFiles: [], addedTests: [], gate: null, head: null }
    : { summary: "sample checked", findings };
  fs.writeFileSync(output, mode === "malformed" ? '{"verdict":"ok","findings":true}' : JSON.stringify(value));
}
`);
  chmodSync(fake, 0o755);
  const env = { ...process.env, HWORKS_CODEX: fake, TEST_CODEX_MODE: mode, TEST_CODEX_DIR: dir };
  const argsFile = join(dir, "args.json");
  const args = { cwd, base, brief, gate: "git diff --exit-code HEAD -- && git show HEAD:sample", reviewers: 1, taskDir: dir };
  function command(name, overrides) {
    writeFileSync(argsFile, JSON.stringify({ ...args, ...overrides }));
    return [runner, name, argsFile];
  }
  function run(name, overrides) {
    return spawnSync(process.execPath, command(name, overrides), { cwd, env, encoding: "utf8", timeout: 10000 });
  }
  return { dir, cwd, base, git, env, run, command };
}

function verdict(result) {
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

test("Codex loop commits writer changes, runs the host gate, and reviews the actual HEAD", t => {
  const fx = fixture(t);
  const value = verdict(fx.run("review-loop"));
  assert.equal(value.state, "clean");
  assert.equal(value.gateBy, "host");
  assert.equal(value.head, fx.git("rev-parse", "HEAD"));
  assert.notEqual(value.head, fx.base);
  assert.equal(fx.git("show", "HEAD:sample"), "changed");
  assert.equal(fx.git("status", "--porcelain"), "");
  assert.equal(readFileSync(join(fx.dir, "calls"), "utf8"), "write\nread\n");
  const artifacts = join(fx.cwd, "artifacts");
  mkdirSync(artifacts);
  const nested = fx.run("review-loop", { taskDir: artifacts });
  assert.equal(nested.status, 1);
  assert.match(nested.stderr, /taskDir must be outside/);
  writeFileSync(join(fx.cwd, "operator-note"), "existing local work");
  const dirty = fx.run("review-loop");
  assert.equal(dirty.status, 1);
  assert.match(dirty.stderr, /requires a clean worktree/);
  assert.equal(fx.git("rev-parse", "HEAD"), value.head);
  assert.equal(fx.git("status", "--porcelain"), "?? operator-note");
});

test("Codex loop feeds a blocking finding to the next writer and re-reviews its commit", t => {
  const fx = fixture(t, "fix");
  const value = verdict(fx.run("review-loop"));
  assert.equal(value.state, "clean");
  assert.equal(value.rounds, 2);
  assert.equal(fx.git("show", "HEAD:sample"), "fixed");
  assert.equal(fx.git("rev-list", "--count", fx.base + "..HEAD"), "2");
});

test("Codex loop never treats a failed host gate or malformed review as clean", t => {
  const fx = fixture(t, "malformed");
  const failedGate = verdict(fx.run("review-loop", { gate: "exit 9" }));
  assert.equal(failedGate.state, "gate-failed");
  assert.match(failedGate.failure.error, /gate.*exit 9/);
  assert.equal(readFileSync(join(fx.dir, "calls"), "utf8"), "write\nwrite\n");
  assert.equal(verdict(fx.run("review-loop")).state, "review-failed");
});

test("Codex loop holds for operator inspection after a forced gate exit", t => {
  const fx = fixture(t);
  const result = fx.run("review-loop", { gate: 'kill -KILL "$$"' });
  assert.equal(result.status, 125, result.stderr);
  assert.equal(result.stdout, "");
  assert.match(result.stderr, /detached descendants may still be active/);
  assert.equal(readFileSync(join(fx.dir, "calls"), "utf8"), "write\n");
});

test("Codex fanout runs the pinned review read-only and rejects a checkout changed during review", t => {
  const good = fixture(t);
  const bad = fixture(t, "stale");
  for (const fx of [good, bad]) {
    const args = {
      targets: [{ key: "branch", cwd: fx.cwd, base: fx.base, head: fx.base, task: "Review." }],
      reviewers: [{}],
    };
    const result = fx.run("review-fanout", args);
    assert.equal(readFileSync(join(fx.dir, "calls"), "utf8"), "read\n");
    if (fx === good) assert.equal(verdict(result).ok, true);
    else {
      assert.equal(result.status, 1);
      assert.match(result.stderr, /worktree changed/);
      assert.equal(result.stdout, "");
    }
  }
});

test("Codex runner terminates the active writer on cancellation without emitting a verdict", async t => {
  const fx = fixture(t, "cancel");
  const proc = spawn(process.execPath, fx.command("review-loop"), { cwd: fx.cwd, env: fx.env });
  t.after(() => proc.kill("SIGTERM"));
  let stderr = "", stdout = "";
  proc.stderr.on("data", buf => { stderr += buf; });
  proc.stdout.on("data", buf => { stdout += buf; });
  const done = once(proc, "close");
  for (let i = 0; !stderr.includes("fake ready") && i < 100; i++) await delay(20);
  assert.match(stderr, /fake ready/);
  proc.kill("SIGTERM");
  assert.equal((await done)[0], 143);
  assert.equal(stdout, "");
  assert.equal(readFileSync(join(fx.dir, "cancelled"), "utf8"), "yes");
});
