// coder -> reviewer -> fix loop to a verdict. Runs as a pi-subagents workflow script:
// a statement body with top-level await and the globals runs, args, state, emit, console.
// Every child runs in one shared worktree (args.cwd, else the launch cwd) on a clean branch checkout.

if (typeof args.brief !== "string" || !args.brief) throw new Error("args.brief (absolute path to the brief file) is required");
if (typeof args.gate !== "string" || !args.gate) throw new Error("args.gate (shell command) is required");
// A ref like HEAD or the branch name moves with the coder's commits and would empty every review diff.
if (typeof args.base !== "string" || !/^[0-9a-f]{7,40}$/i.test(args.base)) throw new Error("args.base must be a commit SHA (7 to 40 hex chars), not a ref");
if (args.cwd !== undefined && (typeof args.cwd !== "string" || !args.cwd)) throw new Error("args.cwd must be a non-empty path");
if (args.coderModel !== undefined && (typeof args.coderModel !== "string" || !args.coderModel)) throw new Error("args.coderModel must be a non-empty model id");
const reviewerCount = args.reviewers === undefined ? 1 : args.reviewers;
if (![0, 1, 2].includes(reviewerCount)) throw new Error("args.reviewers must be 0, 1 or 2");
const maxRounds = args.maxRounds === undefined ? 3 : args.maxRounds;
if (!Number.isInteger(maxRounds) || maxRounds < 1) throw new Error("args.maxRounds must be a positive integer");
const label = typeof args.label === "string" && args.label ? args.label : "review-loop";
const stateKey = args.label ? ("review-loop." + label.replace(/[^A-Za-z0-9._-]/g, "-")).slice(0, 128) : "review-loop";
const hasState = typeof state !== "undefined" && state && typeof state.set === "function";

const coderSchema = {
  type: "object",
  properties: {
    status: { enum: ["done", "blocked"] },
    head: { type: "string", description: "git rev-parse HEAD after your last commit" },
    summary: { type: "string" },
  },
  required: ["status", "head", "summary"],
};

const reviewSchema = {
  type: "object",
  properties: {
    verdict: { enum: ["ok", "blocked"] },
    findings: {
      type: "array",
      items: {
        type: "object",
        properties: {
          severity: { enum: ["blocking", "non-blocking"] },
          file: { type: "string" },
          line: { type: "integer" },
          claim: { type: "string" },
          evidence: { type: "string" },
          origin: { enum: ["prior", "regression", "new"] },
        },
        required: ["severity", "file", "claim", "evidence"],
      },
    },
    gate: { enum: ["passed", "failed"] },
    head: { type: "string" },
  },
  required: ["verdict", "findings"],
};

// A known runtime defect: a host gate that runs past about five seconds can outlive the async runner,
// which exits 0 without a result after the child finished. The gate never reports, so reviewers run it.
const RUNNER_EXIT = /exited with code 0 before writing a result/;
const failureText = (r) => String((r && (r.error || r.output)) || "unknown failure");

const commitRules =
  "Commit on the current branch with new commits only: no amend, rebase, reset, or push. Leave the working tree clean. " +
  "The gate `" + args.gate + "` runs on the host after you finish; a failing gate fails this run, so run it yourself first. " +
  "Return status `blocked` only when the brief cannot be met without a decision you cannot make; put the reason in summary. " +
  "Set head to the output of `git rev-parse HEAD`.";

function coderTask(round, findings, gateFailure) {
  let task = "Read the brief at " + args.brief + " and implement it. " + commitRules;
  if (findings.length) {
    task +=
      "\n\nThis is fix round " + round + ". Reviewers of `git diff " + args.base + "...HEAD` raised these blocking findings. " +
      "Verify each against the code. Fix the ones that hold, adding a test where the finding is a behavior defect. " +
      "For any that do not hold, say why in summary.\n" + JSON.stringify(findings, null, 2);
  }
  if (gateFailure) {
    task +=
      "\n\nThe previous attempt failed its gate or did not finish. It may still have committed work: a run can fail after it finished. " +
      "Before editing, read `git status`, `git log " + args.base + "..HEAD`, and `git diff " + args.base + "...HEAD`. " +
      "If the brief is already met and the gate passes, return status `done` with the current head and make no new commit. " +
      "Otherwise find the cause and fix it. Failure:\n" + gateFailure;
  }
  return task;
}

function reviewerTask(round, prior, priorHead, gateCheck) {
  let task =
    "Review the change on the current branch. Intent: read the brief at " + args.brief + ". " +
    "Diff: run `git diff " + args.base + "...HEAD` in your cwd and read the surrounding code, not only the diff. " +
    "Verify every claim against the code before reporting it. You are read-only: do not edit, commit, or stage anything. ";
  if (typeof args.rubricDir === "string" && args.rubricDir) {
    task += "Apply the rubric at " + args.rubricDir + "/rubric.md and " + args.rubricDir + "/code-quality-review.md. ";
  }
  task +=
    "Mark a finding blocking only when it is a verified defect, a gap against the brief, or a broken gate. " +
    "Return verdict `blocked` if any finding is blocking, else `ok`.";
  if (round > 1) {
    task +=
      "\n\nThis is review round " + round + ", after a fix. Set `origin` on every finding. " +
      "`prior`: one of the findings below that still holds (omit the ones now fixed). " +
      "`regression`: a defect introduced by the fix, `git diff " + (priorHead || args.base) + "...HEAD`. " +
      "`new`: anything else; it is reported but does not block this loop.\n" + JSON.stringify(prior, null, 2);
  }
  if (gateCheck) {
    task +=
      "\n\nThe host gate did not report this round. Run `" + args.gate + "` in your cwd. Set `gate` to `passed` or `failed` " +
      "and `head` to the output of `git rev-parse HEAD`. A failing gate is a blocking finding.";
  }
  return task;
}

// worktree: false overrides a global worktree default so coder commits land on the caller's branch.
function placed(item) {
  item.worktree = false;
  if (args.cwd) item.cwd = args.cwd;
  return item;
}

function launchCoder(key, round, findings, gateFailure) {
  const item = placed({
    key,
    label: label + ": " + key,
    agent: "coder",
    task: coderTask(round, findings, gateFailure),
    gate: args.gate,
    outputSchema: coderSchema,
  });
  if (args.coderModel) item.model = args.coderModel;
  return runs.all([item]);
}

function launchReview(round, prior, priorHead, gateCheck) {
  const items = [];
  for (let i = 1; i <= reviewerCount; i++) {
    const item = placed({
      key: "review-" + round + "-" + i,
      label: label + ": review " + round + "." + i,
      agent: "reviewer",
      task: reviewerTask(round, prior, priorHead, gateCheck),
      outputSchema: reviewSchema,
    });
    if (i === 2 && typeof args.review2Model === "string" && args.review2Model) item.model = args.review2Model;
    items.push(item);
  }
  return runs.all(items);
}

const runLog = [];
let head = null;
let blocking = [];
let nonBlocking = [];
let rounds = 0;
let gateBy = null;

function record(key, result) {
  runLog.push({ key, runId: result && result.runId ? result.runId : null, ok: !!(result && result.ok) });
}

function finish(finalState) {
  return { state: finalState, rounds, head, gateBy, blocking, nonBlocking, runs: runLog };
}

function progress(phase) {
  if (!hasState) return Promise.resolve();
  return state.set(stateKey, { phase, rounds, head, gateBy, blocking: blocking.length, nonBlocking: nonBlocking.length, runs: runLog });
}

let outcome = null;
while (outcome === null) {
  rounds++;
  const priorHead = head;
  const coderKey = rounds === 1 ? "code-1" : "fix-" + rounds;
  let [coded] = await launchCoder(coderKey, rounds, blocking, null);
  record(coderKey, coded);
  let gateCheck = false;
  if (!coded.ok && RUNNER_EXIT.test(failureText(coded))) {
    gateCheck = true;
  } else if (!coded.ok) {
    const retryKey = coderKey + "-retry";
    [coded] = await launchCoder(retryKey, rounds, blocking, failureText(coded));
    record(retryKey, coded);
    if (!coded.ok && RUNNER_EXIT.test(failureText(coded))) {
      gateCheck = true;
    } else if (!coded.ok) {
      outcome = "gate-failed";
      break;
    }
  }
  gateBy = gateCheck ? "reviewers" : "host";
  const report = (coded.ok && coded.structuredOutput) || {};
  if (report.head) head = report.head;
  if (report.status === "blocked") {
    outcome = "blocked";
    break;
  }
  await progress("coded");

  if (reviewerCount === 0) {
    outcome = gateCheck ? "gate-unverified" : "clean";
    break;
  }

  const reviews = await launchReview(rounds, blocking, priorHead, gateCheck);
  blocking = [];
  nonBlocking = [];
  let reviewFailed = false;
  reviews.forEach((review, i) => {
    const reviewer = "review-" + rounds + "-" + (i + 1);
    record(reviewer, review);
    const out = review.ok ? review.structuredOutput : null;
    if (!out || !Array.isArray(out.findings)) {
      reviewFailed = true;
      return;
    }
    const mine = out.findings.map((f) => Object.assign({ reviewer }, f));
    let hard = mine.filter((f) => f.severity === "blocking");
    if (out.verdict === "blocked" && hard.length === 0) {
      hard.push({ reviewer, severity: "blocking", file: "", claim: "Reviewer returned blocked without a blocking finding.", evidence: String(review.output || "").slice(0, 2000) });
    }
    if (gateCheck) {
      if (out.gate === "failed") {
        hard.push({ reviewer, severity: "blocking", origin: "regression", file: "", claim: "The gate fails: " + args.gate, evidence: "Reported by the reviewer that ran it." });
      } else if (out.gate !== "passed") {
        reviewFailed = true;
        return;
      }
      if (typeof out.head === "string" && out.head) head = out.head;
    }
    // After round 1, only unfixed prior findings and regressions block, so the loop converges.
    // A blocking finding without an origin still blocks: an untagged finding must not pass silently.
    const soft = mine.filter((f) => f.severity !== "blocking");
    if (rounds > 1) {
      soft.push(...hard.filter((f) => f.origin === "new").map((f) => Object.assign({}, f, { severity: "non-blocking", downgraded: true })));
      hard = hard.filter((f) => f.origin !== "new");
    }
    blocking.push(...hard);
    nonBlocking.push(...soft);
  });
  await progress("reviewed");

  if (reviewFailed) outcome = "review-failed";
  else if (blocking.length === 0) outcome = "clean";
  else if (rounds >= maxRounds) outcome = "unresolved";
}

await progress(outcome);
return finish(outcome);
