const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "review-fanout.js"), "utf8");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const script = new AsyncFunction("runs", "args", "state", "emit", "console", source);

function deepFreeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}

// results maps a child key to the result it returns; unknown keys fail the test. batches records each runs.all call's keys.
function fakeRuns(results) {
  const calls = [];
  const batches = [];
  function resolve(key, params) {
    calls.push({ key, ...params });
    if (!(key in results)) throw new Error("unexpected child " + key);
    return { runId: "run-" + key, ...results[key] };
  }
  return {
    calls,
    batches,
    runs: {
      run(key, params) {
        return Promise.resolve(resolve(key, params));
      },
      all(items) {
        batches.push(items.map((i) => i.key));
        return Promise.resolve(items.map(({ key, ...params }) => resolve(key, params)));
      },
    },
  };
}

const SHA_A = "a".repeat(40);
const SHA_B = "0123456789abcdef0123456789abcdef01234567";
const targetA = { key: "pr-1", cwd: "/work/pr-1", task: "Review PR 1: add retries.", base: SHA_A };
const targetB = { key: "plan", cwd: "/work/plans", task: "Review plan.md for gaps." };
const baseArgs = { targets: [targetA, targetB], review2Model: "prov/model-b" };

const reviewed = (findings, summary) => ({ ok: true, output: "", structuredOutput: { summary: summary || "looks fine", findings } });
const clean = reviewed([]);
const f = (file, line, claim, extra) => ({ severity: "non-blocking", file, line, claim, evidence: file + ":" + line, ...extra });

function run(results, args) {
  const fake = fakeRuns(results);
  return script(fake.runs, deepFreeze({ ...baseArgs, ...args }), undefined, () => {}, console).then((out) => ({ out, calls: fake.calls, batches: fake.batches }));
}

const allClean = { "pr-1.r1": clean, "pr-1.r2": clean, "plan.r1": clean, "plan.r2": clean };

test("concurrency 1 reviews one target at a time, both reviewers together", async () => {
  const { out, batches } = await run(allClean, { concurrency: 1 });
  assert.deepEqual(batches, [["pr-1.r1", "pr-1.r2"], ["plan.r1", "plan.r2"]]);
  assert.equal(out.ok, true);
  assert.deepEqual(out.targets.map((t) => t.key), ["pr-1", "plan"]);
});

test("concurrency 2 (the default) reviews two targets in one batch", async () => {
  const { out, batches } = await run(allClean);
  assert.deepEqual(batches, [["pr-1.r1", "pr-1.r2", "plan.r1", "plan.r2"]]);
  assert.equal(out.ok, true);
});

test("a third target waits for the next batch", async () => {
  const targetC = { key: "pr-3", cwd: "/work/pr-3", task: "Review PR 3." };
  const { out, batches } = await run({ ...allClean, "pr-3.r1": clean, "pr-3.r2": clean }, { targets: [targetA, targetB, targetC] });
  assert.deepEqual(batches, [["pr-1.r1", "pr-1.r2", "plan.r1", "plan.r2"], ["pr-3.r1", "pr-3.r2"]]);
  assert.deepEqual(out.targets.map((t) => t.key), ["pr-1", "plan", "pr-3"]);
});

test("results map back to the right target and reviewer", async () => {
  const { out } = await run({
    "pr-1.r1": reviewed([f("a.js", 3, "off by one")], "A by one"),
    "pr-1.r2": reviewed([], "A by two"),
    "plan.r1": reviewed([], "B by one"),
    "plan.r2": reviewed([f("plan.md", 9, "no rollback step")], "B by two"),
  });
  assert.deepEqual(out.targets[0].reviewers, [
    { label: "reviewer", model: null, ok: true, runId: "run-pr-1.r1", summary: "A by one", findings: [f("a.js", 3, "off by one")] },
    { label: "review2", model: "prov/model-b", ok: true, runId: "run-pr-1.r2", summary: "A by two", findings: [] },
  ]);
  assert.deepEqual(out.targets[0].merged, [{ ...f("a.js", 3, "off by one"), raisedBy: ["reviewer"] }]);
  assert.deepEqual(out.targets[1].reviewers.map((r) => r.summary), ["B by one", "B by two"]);
  assert.deepEqual(out.targets[1].merged, [{ ...f("plan.md", 9, "no rollback step"), raisedBy: ["review2"] }]);
});

test("default reviewers: the reviewer role model, then review2Model; each runs read-only in the target cwd", async () => {
  const { calls } = await run(allClean, { task: "Intent: harden retries." });
  assert.equal(calls.length, 4);
  for (const c of calls) {
    assert.equal(c.agent, "reviewer", c.key);
    assert.equal(c.worktree, false, c.key);
    assert.equal(c.outputSchema.required.includes("findings"), true, c.key);
    assert.equal(c.acceptance, undefined, c.key);
    assert.equal(c.gate, undefined, c.key);
    assert.match(c.task, /^Intent: harden retries\.\n\n/, c.key);
    assert.match(c.task, /read-only/, c.key);
  }
  const byKey = Object.fromEntries(calls.map((c) => [c.key, c]));
  assert.equal(byKey["pr-1.r1"].model, undefined);
  assert.equal(byKey["pr-1.r2"].model, "prov/model-b");
  assert.equal(byKey["pr-1.r1"].cwd, "/work/pr-1");
  assert.equal(byKey["plan.r2"].cwd, "/work/plans");
  assert.match(byKey["pr-1.r1"].task, /Review PR 1: add retries\./);
  assert.match(byKey["pr-1.r1"].task, new RegExp("git diff " + SHA_A + "\\.\\.\\.HEAD"));
  assert.doesNotMatch(byKey["plan.r1"].task, /git diff/);
  assert.match(byKey["plan.r1"].task, /Review plan\.md for gaps\./);
});

test("explicit reviewers set agent, model and label", async () => {
  const { out, calls } = await run(
    { "pr-1.r1": clean, "pr-1.r2": clean, "pr-1.r3": clean },
    {
      targets: [targetA],
      review2Model: undefined,
      reviewers: [{ agent: "reviewer", model: "prov/x" }, { agent: "auditor", label: "audit" }, { model: "prov/y", label: "y" }],
    },
  );
  assert.deepEqual(calls.map((c) => [c.key, c.agent, c.model]), [
    ["pr-1.r1", "reviewer", "prov/x"],
    ["pr-1.r2", "auditor", undefined],
    ["pr-1.r3", "reviewer", "prov/y"],
  ]);
  assert.deepEqual(out.targets[0].reviewers.map((r) => [r.label, r.model]), [["reviewer-1", "prov/x"], ["audit", null], ["y", "prov/y"]]);
});

test("a custom schema goes to every child and its output comes back whole", async () => {
  const schema = { type: "object", properties: { verdict: { enum: ["ok", "blocked"] } }, required: ["verdict"] };
  const { out, calls } = await run(
    { "plan.r1": { ok: true, structuredOutput: { verdict: "ok" } }, "plan.r2": { ok: true, structuredOutput: { verdict: "blocked" } } },
    { targets: [targetB], schema },
  );
  for (const c of calls) assert.deepEqual(c.outputSchema, schema);
  assert.equal(out.ok, true);
  assert.deepEqual(out.targets[0].reviewers.map((r) => r.structuredOutput), [{ verdict: "ok" }, { verdict: "blocked" }]);
  assert.deepEqual(out.targets[0].merged, []);
});

test("a custom schema keeps non-object output and fails only a missing one", async () => {
  const schema = { type: "array", items: { type: "string" } };
  const { out } = await run(
    { "plan.r1": { ok: true, structuredOutput: ["valid finding"] }, "plan.r2": { ok: true } },
    { targets: [targetB], schema },
  );
  assert.equal(out.ok, false);
  const [r1, r2] = out.targets[0].reviewers;
  assert.equal(r1.ok, true);
  assert.deepEqual(r1.structuredOutput, ["valid finding"]);
  assert.equal(r1.findings, undefined);
  assert.equal(r2.ok, false);
  assert.match(r2.error, /no structured output/);
  assert.deepEqual(out.targets[0].merged, []);
});

test("a custom schema keeps schema-valid null output", async () => {
  const schema = { type: "null" };
  const { out } = await run(
    { "plan.r1": { ok: true, structuredOutput: null }, "plan.r2": { ok: true, structuredOutput: null } },
    { targets: [targetB], schema },
  );
  assert.equal(out.ok, true);
  for (const r of out.targets[0].reviewers) {
    assert.equal(r.ok, true);
    assert.ok(Object.hasOwn(r, "structuredOutput"));
    assert.equal(r.structuredOutput, null);
    assert.equal(r.error, undefined);
  }
});

test("near-identical claims on one line merge across reviewers, and any blocking vote wins", async () => {
  const { out } = await run({
    "pr-1.r1": reviewed([f("src/a.js", 3, "off by one in the loop bound")]),
    "pr-1.r2": reviewed([f("./src/a.js", 3, "Off-by-one in the loop bound.", { severity: "blocking" })]),
    "plan.r1": clean,
    "plan.r2": clean,
  });
  assert.deepEqual(out.targets[0].merged, [
    { ...f("src/a.js", 3, "off by one in the loop bound"), severity: "blocking", raisedBy: ["reviewer", "review2"] },
  ]);
});

test("two different claims on one line stay separate entries in merged", async () => {
  const { out } = await run({
    "pr-1.r1": reviewed([f("a.js", 7, "token is logged in plain text")]),
    "pr-1.r2": reviewed([f("a.js", 7, "missing null check on the response", { fix: "guard res before reading res.body" })]),
    "plan.r1": clean,
    "plan.r2": clean,
  });
  assert.deepEqual(out.targets[0].merged, [
    { ...f("a.js", 7, "token is logged in plain text"), raisedBy: ["reviewer"] },
    { ...f("a.js", 7, "missing null check on the response", { fix: "guard res before reading res.body" }), raisedBy: ["review2"] },
  ]);
});

test("a repeated claim merges once across reviewers and lines, with its own severity", async () => {
  const reviewers = [{ label: "r1" }, { label: "r2" }, { label: "r3" }];
  const { out } = await run(
    {
      "pr-1.r1": reviewed([f("a.js", 3, "race on cache write")]),
      "pr-1.r2": reviewed([f("a.js", 3, "leaks file handle")]),
      "pr-1.r3": reviewed([f("a.js", 4, "Leaks file handle.", { severity: "blocking" })]),
      "plan.r1": clean,
      "plan.r2": clean,
      "plan.r3": clean,
    },
    { reviewers },
  );
  assert.deepEqual(
    out.targets[0].merged.map((m) => [m.line, m.claim, m.severity, m.raisedBy]),
    [
      [3, "race on cache write", "non-blocking", ["r1"]],
      [3, "leaks file handle", "blocking", ["r2", "r3"]],
    ],
  );
});

test("a claim repeated at two lines joins the entry on the same line when one is open", async () => {
  const { out } = await run({
    "pr-1.r1": reviewed([f("a.js", 3, "unchecked error from write"), f("a.js", 9, "unchecked error from write")]),
    "pr-1.r2": reviewed([f("a.js", 9, "Unchecked error from write.")]),
    "plan.r1": clean,
    "plan.r2": clean,
  });
  assert.deepEqual(
    out.targets[0].merged.map((m) => [m.line, m.raisedBy]),
    [
      [3, ["reviewer"]],
      [9, ["reviewer", "review2"]],
    ],
  );
});

test("findings on the same file with near-identical claims merge; different claims or files do not", async () => {
  const { out } = await run({
    "pr-1.r1": reviewed([f("a.js", undefined, "The retry loop never resets the backoff."), f("a.js", 10, "missing test for timeout"), f("b.js", 1, "unused import")]),
    "pr-1.r2": reviewed([f("a.js", 40, "the retry loop never resets the backoff"), f("a.js", 12, "error message is vague"), f("c.js", 1, "unused import")]),
    "plan.r1": clean,
    "plan.r2": clean,
  });
  assert.deepEqual(
    out.targets[0].merged.map((m) => [m.file, m.claim, m.raisedBy]),
    [
      ["a.js", "The retry loop never resets the backoff.", ["reviewer", "review2"]],
      ["a.js", "missing test for timeout", ["reviewer"]],
      ["b.js", "unused import", ["reviewer"]],
      ["a.js", "error message is vague", ["review2"]],
      ["c.js", "unused import", ["review2"]],
    ],
  );
});

test("two findings from one reviewer on the same line stay separate", async () => {
  const { out } = await run({
    "pr-1.r1": reviewed([f("a.js", 3, "off by one"), f("a.js", 3, "shadowed variable")]),
    "pr-1.r2": reviewed([f("a.js", 3, "off by one")]),
    "plan.r1": clean,
    "plan.r2": clean,
  });
  assert.deepEqual(out.targets[0].merged.map((m) => [m.claim, m.raisedBy]), [
    ["off by one", ["reviewer", "review2"]],
    ["shadowed variable", ["reviewer"]],
  ]);
});

test("a failed reviewer is reported for its target, not dropped, and fails the run", async () => {
  const { out } = await run({
    "pr-1.r1": reviewed([f("a.js", 3, "off by one")]),
    "pr-1.r2": { ok: false, error: "model rate limited", output: "" },
    "plan.r1": clean,
    "plan.r2": clean,
  });
  assert.equal(out.ok, false);
  assert.deepEqual(out.targets[0].reviewers[1], { label: "review2", model: "prov/model-b", ok: false, runId: "run-pr-1.r2", error: "model rate limited" });
  assert.deepEqual(out.targets[0].merged.map((m) => m.raisedBy), [["reviewer"]]);
  assert.deepEqual(out.targets[1].reviewers.map((r) => r.ok), [true, true]);
});

test("a reviewer with no structured output is reported as failed", async () => {
  const { out } = await run({
    "pr-1.r1": clean,
    "pr-1.r2": clean,
    "plan.r1": { ok: true, output: "## Verdict\nsound" },
    "plan.r2": { ok: true, output: "", structuredOutput: { summary: "no findings key" } },
  });
  assert.equal(out.ok, false);
  assert.deepEqual(out.targets[1].reviewers.map((r) => [r.ok, r.error]), [
    [false, "reviewer returned no structured output"],
    [false, "reviewer structured output has no findings array"],
  ]);
  assert.equal(out.targets[1].reviewers[0].runId, "run-plan.r1");
  assert.deepEqual(out.targets[1].merged, []);
  assert.deepEqual(out.targets[0].reviewers.map((r) => r.ok), [true, true]);
});

test("empty or missing targets are rejected", async () => {
  await assert.rejects(run({}, { targets: [] }), /args\.targets must be a non-empty array/);
  await assert.rejects(run({}, { targets: undefined }), /args\.targets must be a non-empty array/);
});

test("duplicate target keys are rejected", async () => {
  await assert.rejects(run({}, { targets: [targetA, { ...targetB, key: "pr-1" }] }), /duplicate key 'pr-1'/);
});

test("an invalid target key is rejected", async () => {
  for (const key of ["", "-lead", "has space", "a/b", "x".repeat(121), 7]) {
    await assert.rejects(run({}, { targets: [{ ...targetB, key }] }), /args\.targets\[0\]\.key/, String(key));
  }
});

test("a target cwd that is not absolute is rejected", async () => {
  for (const cwd of ["work/pr-1", "./pr-1", "~/pr-1", "", undefined]) {
    await assert.rejects(run({}, { targets: [{ ...targetA, cwd }] }), /args\.targets\[0\]\.cwd must be an absolute path/, String(cwd));
  }
});

test("a target without a task is rejected", async () => {
  await assert.rejects(run({}, { targets: [{ ...targetA, task: " " }] }), /args\.targets\[0\]\.task/);
});

test("a base that is not a full commit SHA is rejected", async () => {
  for (const base of ["HEAD", "main", "origin/main", "0123abc", "a".repeat(39), "a".repeat(41), "g".repeat(40), ""]) {
    await assert.rejects(run({}, { targets: [{ ...targetA, base }] }), /args\.targets\[0\]\.base must be a full commit SHA/, base);
  }
  for (const base of [SHA_B, "A".repeat(40), "b".repeat(64)]) {
    const { out } = await run({ "pr-1.r1": clean, "pr-1.r2": clean }, { targets: [{ ...targetA, base }] });
    assert.equal(out.ok, true, base);
  }
});

test("omitted reviewers need review2Model so the second review runs on another model", async () => {
  await assert.rejects(run({}, { review2Model: undefined }), /args\.review2Model is required/);
  await assert.rejects(run({}, { review2Model: "" }), /args\.review2Model must be a non-empty model id/);
});

test("invalid reviewers are rejected", async () => {
  await assert.rejects(run({}, { reviewers: [] }), /args\.reviewers must be a non-empty array/);
  await assert.rejects(run({}, { reviewers: ["reviewer"] }), /args\.reviewers\[0\] must be an object/);
  await assert.rejects(run({}, { reviewers: [{ model: "" }] }), /args\.reviewers\[0\]\.model/);
  await assert.rejects(run({}, { reviewers: [{ agent: "" }] }), /args\.reviewers\[0\]\.agent/);
  await assert.rejects(run({}, { reviewers: [{ label: "a" }, { label: "a" }] }), /duplicate label 'a'/);
});

test("invalid concurrency, task, schema or label is rejected", async () => {
  for (const concurrency of [0, -1, 1.5, "2"]) {
    await assert.rejects(run({}, { concurrency }), /args\.concurrency must be a positive integer/, String(concurrency));
  }
  await assert.rejects(run({}, { task: 3 }), /args\.task must be a string/);
  await assert.rejects(run({}, { schema: [] }), /args\.schema must be a JSON schema object/);
  await assert.rejects(run({}, { label: "" }), /args\.label/);
});

test("validation fails before any child launches", async () => {
  const fake = fakeRuns(allClean);
  await assert.rejects(script(fake.runs, deepFreeze({ ...baseArgs, targets: [targetA, { ...targetB, base: "main" }] }), undefined, () => {}, console));
  assert.deepEqual(fake.calls, []);
});

test("source has no nested async functions", () => {
  assert.doesNotMatch(source, /async\s+(function|\(|[A-Za-z_$][\w$]*\s*=>)/);
});

test("taskDir gives each reviewer a unique absolute output file in it", async () => {
  const { calls } = await run(allClean, { taskDir: "/tmp/task/", reviewers: [{ label: "a b" }, { label: "c" }] });
  assert.deepEqual(calls.map((c) => c.output), [
    "/tmp/task/review-fanout-t1-r1-pr-1-a-b.md",
    "/tmp/task/review-fanout-t1-r2-pr-1-c.md",
    "/tmp/task/review-fanout-t2-r1-plan-a-b.md",
    "/tmp/task/review-fanout-t2-r2-plan-c.md",
  ]);
});

test("taskDir outputs stay unique when sanitized or joined names collide", async () => {
  const targets = [
    { key: "x", cwd: "/abs/x", task: "Review x." },
    { key: "x-y", cwd: "/abs/xy", task: "Review x-y." },
  ];
  const reviewers = [{ label: "a b" }, { label: "a-b" }, { label: "y-z" }, { label: "z" }];
  const results = {};
  for (const t of targets) reviewers.forEach((r, i) => (results[t.key + ".r" + (i + 1)] = clean));
  const { calls } = await run(results, { targets, reviewers, taskDir: "/tmp/task", concurrency: 1 });
  const outputs = calls.map((c) => c.output);
  assert.equal(outputs.length, 8);
  assert.equal(new Set(outputs).size, 8);
  assert.ok(outputs.every((o) => /^\/tmp\/task\/[A-Za-z0-9._-]+\.md$/.test(o)));
});

test("taskDir output basenames stay under the filename limit and unique for long names", async () => {
  const targets = [
    { key: "k".repeat(120), cwd: "/abs/a", task: "Review a." },
    { key: "k".repeat(119) + "j", cwd: "/abs/b", task: "Review b." },
  ];
  const reviewers = [{ label: "r".repeat(60) }, { label: "r".repeat(59) + "s" }];
  const results = {};
  for (const t of targets) reviewers.forEach((r, i) => (results[t.key + ".r" + (i + 1)] = clean));
  const { calls } = await run(results, { targets, reviewers, label: "l".repeat(80), taskDir: "/tmp/task", concurrency: 1 });
  const names = calls.map((c) => c.output.slice("/tmp/task/".length));
  assert.equal(names.length, 4);
  assert.equal(new Set(names).size, 4);
  assert.ok(names.every((n) => !n.includes("/") && Buffer.byteLength(n) <= 255), names.join("\n"));
});

test("without taskDir no reviewer gets an output field", async () => {
  const { calls } = await run(allClean);
  assert.ok(calls.every((c) => !("output" in c)));
});

test("a relative or empty taskDir is rejected", async () => {
  await assert.rejects(run(allClean, { taskDir: "task" }), /args.taskDir must be an absolute path/);
  await assert.rejects(run(allClean, { taskDir: "" }), /args.taskDir must be an absolute path/);
});
