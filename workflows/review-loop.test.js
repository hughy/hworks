const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "review-loop.js"), "utf8");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const script = new AsyncFunction("runs", "args", "state", "emit", "console", source);

function deepFreeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}

// results maps a child key to the result it returns; unknown keys fail the test.
function fakeRuns(results) {
  const calls = [];
  function resolve(key, params) {
    calls.push({ key, ...params });
    if (!(key in results)) throw new Error("unexpected child " + key);
    return { runId: "run-" + key, ...results[key] };
  }
  return {
    calls,
    runs: {
      run(key, params) {
        return Promise.resolve(resolve(key, params));
      },
      all(items) {
        return Promise.resolve(items.map(({ key, ...params }) => resolve(key, params)));
      },
    },
  };
}

function fakeState() {
  const sets = [];
  return {
    sets,
    set: (key, value) => {
      // The runtime rejects keys outside this pattern.
      assert.match(key, /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/);
      sets.push({ key, value });
      return Promise.resolve();
    },
    get: () => Promise.resolve(undefined),
  };
}

const baseArgs = { brief: "/tmp/brief.md", gate: "npm test", base: "0123abc", reviewers: 1, rubricDir: "/r" };
const coded = (head) => ({ ok: true, output: "", structuredOutput: { status: "done", head, summary: "s" } });
const clean = { ok: true, output: "", structuredOutput: { verdict: "ok", findings: [] } };
const finding = { severity: "blocking", file: "a.js", line: 3, claim: "off by one", evidence: "a.js:3" };
const note = { severity: "non-blocking", file: "b.js", line: 1, claim: "naming", evidence: "b.js:1" };
const blocked = { ok: true, output: "", structuredOutput: { verdict: "blocked", findings: [finding, note] } };

function run(results, args, state) {
  const fake = fakeRuns(results);
  return script(fake.runs, deepFreeze({ ...baseArgs, ...args }), state, () => {}, console).then((out) => ({ out, calls: fake.calls }));
}

test("clean on first review", async () => {
  const state = fakeState();
  const { out, calls } = await run({ "code-1": coded("abc"), "review-1-1": clean }, { label: "fix: issue 12" }, state);
  assert.equal(out.state, "clean");
  assert.equal(out.rounds, 1);
  assert.equal(out.head, "abc");
  assert.deepEqual(out.blocking, []);
  assert.deepEqual(out.runs, [
    { key: "code-1", runId: "run-code-1", ok: true },
    { key: "review-1-1", runId: "run-review-1-1", ok: true },
  ]);
  assert.equal(calls[0].agent, "coder");
  assert.deepEqual(calls[0].acceptance, { level: "verified", verify: [{ id: "gate", command: "npm test", timeoutMs: 600000 }], report: "on" });
  assert.equal(calls[0].gate, undefined);
  assert.ok(calls[0].outputSchema);
  assert.equal(calls[0].worktree, false);
  assert.equal(calls[0].model, undefined);
  assert.equal(calls[0].cwd, undefined);
  assert.equal(calls[1].worktree, false);
  assert.equal(calls[1].agent, "reviewer");
  assert.equal(calls[1].gate, undefined);
  assert.equal(calls[1].acceptance, undefined);
  assert.match(calls[1].task, /git diff 0123abc\.\.\.HEAD/);
  assert.match(calls[1].task, /\/r\/rubric\.md/);
  assert.match(calls[1].task, /added flag, knob, field, timer, guard, or tool that the brief did not require and nothing in the diff or brief justifies/);
  assert.ok(state.sets.length > 0);
  assert.equal(state.sets.at(-1).key, "review-loop.fix--issue-12");
  assert.equal(state.sets.at(-1).value.phase, "clean");
});

test("blocking then clean runs a fix round with the findings", async () => {
  const { out, calls } = await run({
    "code-1": coded("a1"),
    "review-1-1": blocked,
    "fix-2": coded("a2"),
    "review-2-1": clean,
  });
  assert.equal(out.state, "clean");
  assert.equal(out.rounds, 2);
  assert.equal(out.head, "a2");
  const fix = calls.find((c) => c.key === "fix-2");
  assert.deepEqual(fix.acceptance, { level: "verified", verify: [{ id: "gate", command: "npm test", timeoutMs: 600000 }], report: "on" });
  assert.match(fix.task, /off by one/);
  assert.doesNotMatch(fix.task, /naming/);
  assert.deepEqual(calls.map((c) => c.key), ["code-1", "review-1-1", "fix-2", "review-2-1"]);
});

test("maxRounds exhausted leaves the loop unresolved", async () => {
  const { out, calls } = await run(
    { "code-1": coded("a1"), "review-1-1": blocked, "fix-2": coded("a2"), "review-2-1": blocked },
    { maxRounds: 2 },
  );
  assert.equal(out.state, "unresolved");
  assert.equal(out.rounds, 2);
  assert.equal(out.blocking.length, 1);
  assert.equal(out.blocking[0].claim, "off by one");
  assert.equal(out.nonBlocking.length, 1);
  assert.equal(calls.length, 4);
});

test("after round 1, new blocking findings are downgraded and the loop converges", async () => {
  const fresh = { ...finding, claim: "unicode edge case", origin: "new" };
  const { out, calls } = await run({
    "code-1": coded("a1"),
    "review-1-1": blocked,
    "fix-2": coded("a2"),
    "review-2-1": { ok: true, output: "", structuredOutput: { verdict: "blocked", findings: [fresh] } },
  });
  assert.equal(out.state, "clean");
  assert.deepEqual(out.blocking, []);
  assert.equal(out.nonBlocking.length, 1);
  assert.equal(out.nonBlocking[0].claim, "unicode edge case");
  assert.equal(out.nonBlocking[0].severity, "non-blocking");
  assert.equal(out.nonBlocking[0].downgraded, true);
  const review2 = calls.find((c) => c.key === "review-2-1");
  assert.match(review2.task, /off by one/);
  assert.match(review2.task, /git diff a1\.\.\.HEAD/);
  assert.doesNotMatch(calls.find((c) => c.key === "review-1-1").task, /origin/);
});

test("after round 1, unfixed prior findings, regressions, and untagged findings still block", async () => {
  for (const origin of ["prior", "regression", undefined]) {
    const f = origin ? { ...finding, origin } : finding;
    const { out } = await run(
      {
        "code-1": coded("a1"),
        "review-1-1": blocked,
        "fix-2": coded("a2"),
        "review-2-1": { ok: true, output: "", structuredOutput: { verdict: "blocked", findings: [f] } },
      },
      { maxRounds: 2 },
    );
    assert.equal(out.state, "unresolved", String(origin));
    assert.equal(out.blocking.length, 1, String(origin));
  }
});

test("round 1 blocks on any blocking finding, whatever its origin", async () => {
  const { out } = await run(
    { "code-1": coded("a1"), "review-1-1": { ok: true, output: "", structuredOutput: { verdict: "blocked", findings: [{ ...finding, origin: "new" }] } } },
    { maxRounds: 1 },
  );
  assert.equal(out.state, "unresolved");
  assert.equal(out.blocking.length, 1);
});

const runnerExit = { ok: false, error: "Async runner process 1 exited with code 0 before writing a result. Marked run failed by stale-run reconciliation." };
const gated = (gate, head) => ({ ok: true, output: "", structuredOutput: { verdict: "ok", findings: [], gate, head } });

test("a runner exit skips the retry and reviewers run the gate", async () => {
  const { out, calls } = await run({ "code-1": runnerExit, "review-1-1": gated("passed", "h1") });
  assert.equal(out.state, "clean");
  assert.equal(out.gateBy, "reviewers");
  assert.equal(out.head, "h1");
  assert.deepEqual(calls.map((c) => c.key), ["code-1", "review-1-1"]);
  assert.match(calls[1].task, /Run `npm test`/);
});

test("a reviewer-run gate that fails blocks and starts a fix round", async () => {
  const { out, calls } = await run({
    "code-1": runnerExit,
    "review-1-1": gated("failed", "h1"),
    "fix-2": coded("h2"),
    "review-2-1": clean,
  });
  assert.equal(out.state, "clean");
  assert.equal(out.gateBy, "host");
  assert.match(calls.find((c) => c.key === "fix-2").task, /The gate fails: npm test/);
  assert.doesNotMatch(calls.find((c) => c.key === "review-2-1").task, /Run `npm test`/);
});

test("a reviewer that does not report the gate fails the review", async () => {
  const { out } = await run({ "code-1": runnerExit, "review-1-1": clean });
  assert.equal(out.state, "review-failed");
});

test("a runner exit with no reviewers is gate-unverified", async () => {
  const { out } = await run({ "code-1": runnerExit }, { reviewers: 0 });
  assert.equal(out.state, "gate-unverified");
});

test("a runner exit on the retry also hands the gate to reviewers", async () => {
  const { out, calls } = await run({
    "code-1": { ok: false, error: "gate failed: 2 tests" },
    "code-1-retry": runnerExit,
    "review-1-1": gated("passed", "h9"),
  });
  assert.equal(out.state, "clean");
  assert.equal(out.head, "h9");
  assert.deepEqual(calls.map((c) => c.key), ["code-1", "code-1-retry", "review-1-1"]);
});

const gateTimeout = { ok: false, error: "Acceptance verification 'gate' timed-out." };

test("gateTimeoutMs sets the gate timeout and defaults to 600000", async () => {
  const dflt = await run({ "code-1": coded("a"), "review-1-1": clean });
  assert.equal(dflt.calls[0].acceptance.verify[0].timeoutMs, 600000);
  assert.match(dflt.calls[0].task, /600 s timeout/);
  const custom = await run({ "code-1": coded("a"), "review-1-1": clean }, { gateTimeoutMs: 900000 });
  assert.equal(custom.calls[0].acceptance.verify[0].timeoutMs, 900000);
  assert.match(custom.calls[0].task, /900 s timeout/);
});

test("an invalid gateTimeoutMs is rejected", async () => {
  for (const gateTimeoutMs of [0, -1, 1.5, "600000", null]) {
    await assert.rejects(run({}, { gateTimeoutMs }), /args\.gateTimeoutMs/, String(gateTimeoutMs));
  }
});

test("a gate timeout skips the retry and reviewers run the gate", async () => {
  const { out, calls } = await run({ "code-1": gateTimeout, "review-1-1": gated("passed", "t1") });
  assert.equal(out.state, "clean");
  assert.equal(out.gateBy, "reviewers");
  assert.equal(out.head, "t1");
  assert.deepEqual(calls.map((c) => c.key), ["code-1", "review-1-1"]);
  assert.match(calls[1].task, /timed out/);
  assert.match(calls[1].task, /Run `npm test`/);
});

test("a gate timeout on the retry also hands the gate to reviewers", async () => {
  const { out, calls } = await run({
    "code-1": { ok: false, error: "Acceptance verification 'gate' failed." },
    "code-1-retry": gateTimeout,
    "review-1-1": gated("passed", "t2"),
  });
  assert.equal(out.state, "clean");
  assert.deepEqual(calls.map((c) => c.key), ["code-1", "code-1-retry", "review-1-1"]);
});

test("a gate timeout with no reviewers is gate-unverified", async () => {
  const { out, calls } = await run({ "code-1": gateTimeout }, { reviewers: 0 });
  assert.equal(out.state, "gate-unverified");
  assert.equal(out.gateBy, "reviewers");
  assert.deepEqual(calls.map((c) => c.key), ["code-1"]);
});

test("a gate failure that is not a timeout still retries", async () => {
  const { out, calls } = await run({
    "code-1": { ok: false, error: "Acceptance verification 'gate' failed." },
    "code-1-retry": { ok: false, error: "Acceptance verification 'lint' timed-out." },
  });
  assert.equal(out.state, "gate-failed");
  assert.deepEqual(calls.map((c) => c.key), ["code-1", "code-1-retry"]);
});

test("reviewers 0 runs the gated coder only", async () => {
  const { out, calls } = await run({ "code-1": coded("abc") }, { reviewers: 0 });
  assert.equal(out.state, "clean");
  assert.deepEqual(calls.map((c) => c.key), ["code-1"]);
});

test("review2Model goes to the second reviewer only", async () => {
  const { out, calls } = await run(
    { "code-1": coded("abc"), "review-1-1": clean, "review-1-2": clean },
    { reviewers: 2, review2Model: "prov/model-b" },
  );
  assert.equal(out.state, "clean");
  const [r1, r2] = calls.filter((c) => c.agent === "reviewer");
  assert.equal(r1.model, undefined);
  assert.equal(r2.model, "prov/model-b");
});

test("every child runs in the shared worktree, never an isolated one", async () => {
  const { calls } = await run(
    {
      "code-1": { ok: false, error: "gate failed" },
      "code-1-retry": coded("a1"),
      "review-1-1": blocked,
      "review-1-2": clean,
      "fix-2": coded("a2"),
      "review-2-1": clean,
      "review-2-2": clean,
    },
    { reviewers: 2 },
  );
  assert.equal(calls.length, 7);
  for (const c of calls) assert.equal(c.worktree, false, c.key);
});

test("a base that is not a commit SHA is rejected", async () => {
  for (const base of ["HEAD", "main", "origin/main", "abc12", "0123abcz", "a".repeat(41)]) {
    await assert.rejects(run({}, { base }), /args\.base/, base);
  }
  for (const base of ["0123abc", "A".repeat(40)]) {
    const { out } = await run({ "code-1": coded("x"), "review-1-1": clean }, { base });
    assert.equal(out.state, "clean");
  }
});

test("coderModel goes to coder launches only", async () => {
  const { calls } = await run(
    {
      "code-1": { ok: false, error: "gate failed" },
      "code-1-retry": coded("a1"),
      "review-1-1": blocked,
      "review-1-2": clean,
      "fix-2": coded("a2"),
      "review-2-1": clean,
      "review-2-2": clean,
    },
    { reviewers: 2, coderModel: "prov/coder:low", review2Model: "prov/model-b" },
  );
  const coders = calls.filter((c) => c.agent === "coder");
  const reviewers = calls.filter((c) => c.agent === "reviewer");
  assert.equal(coders.length, 3);
  for (const c of coders) assert.equal(c.model, "prov/coder:low", c.key);
  assert.deepEqual(reviewers.map((c) => c.model), [undefined, "prov/model-b", undefined, "prov/model-b"]);
});

test("cwd goes to every child when set", async () => {
  const { calls } = await run(
    { "code-1": coded("a1"), "review-1-1": blocked, "fix-2": coded("a2"), "review-2-1": clean },
    { cwd: "/work/tree" },
  );
  assert.equal(calls.length, 4);
  for (const c of calls) assert.equal(c.cwd, "/work/tree", c.key);
});

test("a non-string cwd, coderModel, or preRead is rejected", async () => {
  await assert.rejects(run({}, { cwd: 3 }), /args\.cwd/);
  await assert.rejects(run({}, { coderModel: "" }), /args\.coderModel/);
  await assert.rejects(run({}, { preRead: "" }), /args\.preRead/);
  await assert.rejects(run({}, { preRead: 7 }), /args\.preRead/);
});

test("preRead opens the reviewer task with the pre-read command, before the diff", async () => {
  const { calls } = await run({ "code-1": coded("a1"), "review-1-1": clean }, { preRead: "/h/scripts/review-pre-read.py" });
  const task = calls[1].task;
  assert.ok(task.startsWith("Pre-read: run `python3 /h/scripts/review-pre-read.py 0123abc HEAD` in your cwd"), task);
  assert.ok(task.indexOf("git diff 0123abc...HEAD") > task.indexOf("review-pre-read.py"));
  assert.doesNotMatch(calls[0].task, /review-pre-read/);
  const { calls: without } = await run({ "code-1": coded("a1"), "review-1-1": clean });
  assert.ok(without[1].task.startsWith("Review the change"), without[1].task);
});

test("two gate failures in a row stop with gate-failed", async () => {
  const { out, calls } = await run({
    "code-1": { ok: false, error: "gate failed: 2 tests" },
    "code-1-retry": { ok: false, error: "gate failed again" },
  });
  assert.equal(out.state, "gate-failed");
  assert.deepEqual(calls.map((c) => c.key), ["code-1", "code-1-retry"]);
  assert.match(calls[1].task, /gate failed: 2 tests/);
  assert.match(calls[1].task, /git log 0123abc\.\.HEAD/);
  assert.match(calls[1].task, /make no new commit/);
  assert.deepEqual(out.runs.map((r) => r.ok), [false, false]);
});

test("one gate failure is retried and the loop continues", async () => {
  const { out } = await run({
    "code-1": { ok: false, error: "gate failed" },
    "code-1-retry": coded("r1"),
    "review-1-1": clean,
  });
  assert.equal(out.state, "clean");
  assert.equal(out.head, "r1");
});

test("coder status blocked stops the loop", async () => {
  const { out, calls } = await run({
    "code-1": { ok: true, structuredOutput: { status: "blocked", head: "h", summary: "needs a decision" } },
  });
  assert.equal(out.state, "blocked");
  assert.equal(calls.length, 1);
});

test("no state global is tolerated", async () => {
  const { out } = await run({ "code-1": coded("abc"), "review-1-1": clean }, {}, undefined);
  assert.equal(out.state, "clean");
});

test("source has no nested async functions", () => {
  assert.doesNotMatch(source, /async\s+(function|\(|[A-Za-z_$][\w$]*\s*=>)/);
});

test("taskDir gives each child a unique absolute output file in it", async () => {
  const { calls } = await run(
    {
      "code-1": coded("a"),
      "review-1-1": blocked,
      "review-1-2": clean,
      "fix-2": { ok: false, error: "gate failed" },
      "fix-2-retry": coded("b"),
      "review-2-1": clean,
      "review-2-2": clean,
    },
    { label: "unit: 7", reviewers: 2, taskDir: "/tmp/task" },
  );
  assert.deepEqual(calls.map((c) => c.output), [
    "/tmp/task/unit--7-r1-coder.md",
    "/tmp/task/unit--7-r1-reviewer-1.md",
    "/tmp/task/unit--7-r1-reviewer-2.md",
    "/tmp/task/unit--7-r2-coder.md",
    "/tmp/task/unit--7-r2-coder-retry.md",
    "/tmp/task/unit--7-r2-reviewer-1.md",
    "/tmp/task/unit--7-r2-reviewer-2.md",
  ]);
});

test("taskDir output basenames stay under the filename limit for a long label", async () => {
  const { calls } = await run(
    { "code-1": coded("a"), "review-1-1": clean, "review-1-2": clean },
    { label: "x".repeat(256), reviewers: 2, taskDir: "/tmp/task" },
  );
  const names = calls.map((c) => c.output.slice("/tmp/task/".length));
  assert.equal(names.length, 3);
  assert.equal(new Set(names).size, 3);
  assert.ok(names.every((n) => !n.includes("/") && Buffer.byteLength(n) <= 255), names.join("\n"));
});

test("without taskDir no child gets an output field", async () => {
  const { calls } = await run({ "code-1": coded("a"), "review-1-1": clean });
  assert.ok(calls.every((c) => !("output" in c)));
});

test("a relative or empty taskDir is rejected", async () => {
  await assert.rejects(run({}, { taskDir: "task" }), /args.taskDir must be an absolute path/);
  await assert.rejects(run({}, { taskDir: "" }), /args.taskDir must be an absolute path/);
});
