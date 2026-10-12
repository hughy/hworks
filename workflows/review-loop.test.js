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
  assert.equal(calls[0].gate, "npm test");
  assert.ok(calls[0].outputSchema);
  assert.equal(calls[0].worktree, false);
  assert.equal(calls[0].model, undefined);
  assert.equal(calls[0].cwd, undefined);
  assert.equal(calls[1].worktree, false);
  assert.equal(calls[1].agent, "reviewer");
  assert.equal(calls[1].gate, undefined);
  assert.match(calls[1].task, /git diff 0123abc\.\.\.HEAD/);
  assert.match(calls[1].task, /\/r\/rubric\.md/);
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
  assert.equal(fix.gate, "npm test");
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

test("a non-string cwd or coderModel is rejected", async () => {
  await assert.rejects(run({}, { cwd: 3 }), /args\.cwd/);
  await assert.rejects(run({}, { coderModel: "" }), /args\.coderModel/);
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
