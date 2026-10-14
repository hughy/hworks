const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const realScript = path.join(__dirname, "..", "scripts", "review-loop-args.sh");

// A copy of the script beside a stub models.sh that prints $MODELS_SHOW, plus a repo with a branch ahead of main.
function fixture() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "review-loop-args-"));
  const root = path.join(dir, "root");
  fs.mkdirSync(path.join(root, "scripts"), { recursive: true });
  fs.copyFileSync(realScript, path.join(root, "scripts", "review-loop-args.sh"));
  fs.writeFileSync(path.join(root, "scripts", "models.sh"), '#!/usr/bin/env bash\nprintf "%s\\n" "$MODELS_SHOW"\n', { mode: 0o755 });
  const repo = path.join(dir, "repo");
  fs.mkdirSync(repo);
  const git = (...a) => spawnSync("git", ["-c", "user.name=t", "-c", "user.email=t@t", ...a], { cwd: repo, encoding: "utf8" }).stdout.trim();
  git("init", "-q", "-b", "main");
  git("commit", "-q", "--allow-empty", "-m", "one");
  const mainSha = git("rev-parse", "HEAD");
  git("checkout", "-q", "-b", "work");
  git("commit", "-q", "--allow-empty", "-m", "two");
  const headSha = git("rev-parse", "HEAD");
  const brief = path.join(dir, "brief.md");
  fs.writeFileSync(brief, "goal\n");
  return { root, repo, brief, mainSha, headSha };
}

function show(models) {
  const lines = ["profile: test"];
  for (const role of ["coder", "explorer", "reviewer", "synthesizer"]) lines.push(role + "  " + (models[role] || "(session model)"));
  for (const slot of ["review2", "exhaustive"]) lines.push(slot + "  " + (models[slot] || "(session model)") + " (slot)");
  return lines.join("\n");
}

function runArgs(fx, argv, { models = {}, env = {}, cwd = fx.repo } = {}) {
  const fullEnv = { ...process.env, MODELS_SHOW: show(models) };
  delete fullEnv.PI_PROVIDER;
  delete fullEnv.PI_MODEL;
  Object.assign(fullEnv, env);
  const r = spawnSync("bash", [path.join(fx.root, "scripts", "review-loop-args.sh"), ...argv], { cwd, env: fullEnv, encoding: "utf8" });
  return { status: r.status, stderr: r.stderr, json: r.status === 0 ? JSON.parse(r.stdout) : null };
}

const pinned = { coder: "p/coder", reviewer: "p/rev", review2: "q/rev2", exhaustive: "q/big:medium" };

test("base resolves to the merge-base SHA in the given worktree, which is emitted as cwd", () => {
  const fx = fixture();
  const r = runArgs(fx, [fx.brief, "true", "main", "standard", fx.repo], { models: pinned, cwd: os.tmpdir() });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.json.base, fx.mainSha);
  assert.equal(r.json.cwd, fs.realpathSync(fx.repo));
  const h = runArgs(fx, [fx.brief, "true", "HEAD", "standard", fx.repo], { models: pinned, cwd: os.tmpdir() });
  assert.equal(h.json.base, fx.headSha);
});

test("without a worktree argument the base resolves in the current directory and no cwd is emitted", () => {
  const fx = fixture();
  const r = runArgs(fx, [fx.brief, "true", "main", "standard"], { models: pinned });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.json.base, fx.mainSha);
  assert.equal("cwd" in r.json, false);
});

test("a review ledger in the task dir moves the base to the furthest covered commit", () => {
  const fx = fixture();
  const task = path.join(path.dirname(fx.repo), "task");
  const rr = path.join(__dirname, "..", "scripts", "review-range.py");
  const rec = spawnSync("python3", [rr, "record", task, "main", fx.mainSha, fx.headSha, "review-loop", "--cwd", fx.repo], { encoding: "utf8" });
  assert.equal(rec.status, 0, rec.stderr);
  fs.copyFileSync(rr, path.join(fx.root, "scripts", "review-range.py"));
  const r = runArgs(fx, [fx.brief, "true", "main", "standard", fx.repo, task], { models: pinned });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.json.base, fx.headSha);
  const none = runArgs(fx, [fx.brief, "true", "main", "standard", fx.repo, path.join(path.dirname(fx.repo), "empty-task")], { models: pinned });
  assert.equal(none.json.base, fx.mainSha);
});

test("a ledger the script cannot read fails instead of reviewing from it", () => {
  const fx = fixture();
  const task = path.join(path.dirname(fx.repo), "task");
  fs.mkdirSync(task);
  fs.writeFileSync(path.join(task, "reviewed.tsv"), "");
  fs.writeFileSync(path.join(fx.root, "scripts", "review-range.py"), "import sys\nsys.exit(1)\n");
  const r = runArgs(fx, [fx.brief, "true", "main", "standard", fx.repo, task], { models: pinned });
  assert.equal(r.status, 2);
  assert.match(r.stderr, /review-range\.py base failed/);
});

test("an unknown base ref fails", () => {
  const fx = fixture();
  const r = runArgs(fx, [fx.brief, "true", "no-such-ref", "standard", fx.repo], { models: pinned });
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /no-such-ref/);
});

test("effort sets the coder model", () => {
  const fx = fixture();
  const quick = runArgs(fx, [fx.brief, "true", "main", "quick", fx.repo], { models: { ...pinned, coder: "p/coder:high" } });
  assert.equal(quick.json.coderModel, "p/coder:low");
  assert.equal(quick.json.reviewers, 0);
  const quickMax = runArgs(fx, [fx.brief, "true", "main", "quick", fx.repo], { models: { ...pinned, coder: "p/coder:max" } });
  assert.equal(quickMax.json.coderModel, "p/coder:low");
  const standard = runArgs(fx, [fx.brief, "true", "main", "standard", fx.repo], { models: pinned });
  assert.equal("coderModel" in standard.json, false);
  const exhaustive = runArgs(fx, [fx.brief, "true", "main", "exhaustive", fx.repo], { models: pinned });
  assert.equal(exhaustive.json.coderModel, "q/big:medium");
  assert.equal(exhaustive.json.review2Model, "q/rev2");
  assert.equal(exhaustive.stderr, "");
});

test("session-model slots resolve from PI_PROVIDER and PI_MODEL", () => {
  const fx = fixture();
  const env = { PI_PROVIDER: "s", PI_MODEL: "sess" };
  const quick = runArgs(fx, [fx.brief, "true", "main", "quick", fx.repo], { models: { reviewer: "p/rev" }, env });
  assert.equal(quick.json.coderModel, "s/sess:low");
  const ex = runArgs(fx, [fx.brief, "true", "main", "exhaustive", fx.repo], { models: { reviewer: "p/rev" }, env });
  assert.equal(ex.json.review2Model, "s/sess");
  assert.equal(ex.json.coderModel, "s/sess");
  assert.equal(ex.stderr, "");
});

test("an unresolvable session review2 emits no review2Model and warns", () => {
  const fx = fixture();
  const r = runArgs(fx, [fx.brief, "true", "main", "exhaustive", fx.repo], { models: { ...pinned, review2: "" } });
  assert.equal(r.status, 0, r.stderr);
  assert.equal("review2Model" in r.json, false);
  assert.match(r.stderr, /PI_PROVIDER/);
  assert.match(r.stderr, /both reviews run on one model/);
});

test("the equality warning compares the models both reviewers run", () => {
  const fx = fixture();
  const sameViaSession = runArgs(fx, [fx.brief, "true", "main", "exhaustive", fx.repo], {
    models: { ...pinned, reviewer: "s/sess", review2: "" },
    env: { PI_PROVIDER: "s", PI_MODEL: "sess" },
  });
  assert.match(sameViaSession.stderr, /both reviews run on one model/);
  const sameIgnoringThinking = runArgs(fx, [fx.brief, "true", "main", "exhaustive", fx.repo], {
    models: { ...pinned, reviewer: "s/sess:high", review2: "" },
    env: { PI_PROVIDER: "s", PI_MODEL: "sess" },
  });
  assert.match(sameIgnoringThinking.stderr, /both reviews run on one model/);
  const differ = runArgs(fx, [fx.brief, "true", "main", "exhaustive", fx.repo], {
    models: { ...pinned, reviewer: "", review2: "q/rev2" },
    env: { PI_PROVIDER: "s", PI_MODEL: "sess" },
  });
  assert.doesNotMatch(differ.stderr, /both reviews run on one model/);
});

test("a task dir is created and emitted as an absolute taskDir", () => {
  const fx = fixture();
  const none = runArgs(fx, [fx.brief, "true", "main", "standard", fx.repo], { models: pinned });
  assert.equal("taskDir" in none.json, false);
  const r = runArgs(fx, [fx.brief, "true", "main", "standard", fx.repo, "out/u1"], { models: pinned });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.json.taskDir, path.join(fs.realpathSync(fx.repo), "out", "u1"));
  assert.ok(fs.statSync(r.json.taskDir).isDirectory());
});

test("GATE_TIMEOUT_MS sets gateTimeoutMs; unset emits none; invalid fails", () => {
  const fx = fixture();
  const set = runArgs(fx, [fx.brief, "true", "main", "standard", fx.repo], { models: pinned, env: { GATE_TIMEOUT_MS: "900000" } });
  assert.equal(set.status, 0, set.stderr);
  assert.equal(set.json.gateTimeoutMs, 900000);
  const unset = runArgs(fx, [fx.brief, "true", "main", "standard", fx.repo], { models: pinned, env: { GATE_TIMEOUT_MS: "" } });
  assert.equal(unset.status, 0, unset.stderr);
  assert.equal("gateTimeoutMs" in unset.json, false);
  for (const bad of ["0", "-5", "1.5", "10s"]) {
    const r = runArgs(fx, [fx.brief, "true", "main", "standard", fx.repo], { models: pinned, env: { GATE_TIMEOUT_MS: bad } });
    assert.notEqual(r.status, 0, bad);
    assert.match(r.stderr, /GATE_TIMEOUT_MS/, bad);
  }
});
