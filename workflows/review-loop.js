// coder -> reviewer -> fix loop to a verdict. Runs as a pi-subagents workflow script:
// a statement body with top-level await and the globals runs, args, state, emit, console.
// Every child runs in one shared worktree (args.cwd, else the launch cwd) on a clean branch checkout.

if (typeof args.brief !== "string" || !args.brief) throw new Error("args.brief (absolute path to the brief file) is required");
if (typeof args.gate !== "string" || !args.gate) throw new Error("args.gate (shell command) is required");
// A ref like HEAD or the branch name moves with the coder's commits and would empty every review diff.
if (typeof args.base !== "string" || !/^[0-9a-f]{7,40}$/i.test(args.base)) throw new Error("args.base must be a commit SHA (7 to 40 hex chars), not a ref");
if (args.cwd !== undefined && (typeof args.cwd !== "string" || !args.cwd)) throw new Error("args.cwd must be a non-empty path");
if (args.taskDir !== undefined && (typeof args.taskDir !== "string" || !/^(?:\/|[A-Za-z]:[\\/])/.test(args.taskDir))) throw new Error("args.taskDir must be an absolute path");
if (args.coderModel !== undefined && (typeof args.coderModel !== "string" || !args.coderModel)) throw new Error("args.coderModel must be a non-empty model id");
if (args.preRead !== undefined && (typeof args.preRead !== "string" || !args.preRead)) throw new Error("args.preRead must be a non-empty path to scripts/review-pre-read.py");
const gateTimeoutMs = args.gateTimeoutMs === undefined ? 600000 : args.gateTimeoutMs;
if (!Number.isInteger(gateTimeoutMs) || gateTimeoutMs < 1) throw new Error("args.gateTimeoutMs must be a positive integer (milliseconds)");
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
// A gate that outlives gateTimeoutMs says nothing about the code the coder committed, so reviewers run it too.
const GATE_TIMEOUT = /Acceptance verification 'gate' timed-out\./;
const gateUnreported = (r) => !r.ok && (RUNNER_EXIT.test(failureText(r)) || GATE_TIMEOUT.test(failureText(r)));
const failureText = (r) => String((r && (r.error || r.output)) || "unknown failure");
// The run hit its own deadline, so its work may be partial; a retry with the same brief would hit it again.
const RUN_TIMEOUT = /Subagent timed out after \d+ms\./;
const runTimedOut = (r) => !r.ok && (r.timedOut === true || RUN_TIMEOUT.test(String(r.error || "") + "\n" + String(r.output || "")));
const GATE_FAILED = /Acceptance verification 'gate' failed/;

const commitRules =
  "Commit on the current branch with new commits only: no amend, rebase, reset, or push. Leave the working tree clean. " +
  "The gate `" + args.gate + "` runs on the host after you finish with a " + Math.ceil(gateTimeoutMs / 1000) + " s timeout; " +
  "a failing gate fails this run, so run it yourself first. " +
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
  let task = "";
  if (args.preRead) {
    task +=
      "Pre-read: run `python3 " + args.preRead + " " + args.base + " HEAD` in your cwd and read its output before the diff. " +
      "It is a map of the change: removed or renamed names with their surviving references, related tests, and the diff. " +
      "Verify a lead there from the code; do not report it from the list.\n\n";
  }
  task +=
    "Review the change on the current branch. Intent: read the brief at " + args.brief + ". " +
    "Diff: run `git diff " + args.base + "...HEAD` in your cwd and read the surrounding code, not only the diff. " +
    "Verify every claim against the code before reporting it. You are read-only: do not edit, commit, or stage anything. ";
  if (typeof args.rubricDir === "string" && args.rubricDir) {
    task += "Apply the rubric at " + args.rubricDir + "/rubric.md and " + args.rubricDir + "/code-quality-review.md. ";
  }
  task +=
    "Mark a finding blocking only when it is a verified defect, a gap against the brief, a broken gate, " +
    "or an added flag, knob, field, timer, guard, or tool that the brief did not require and nothing in the diff or brief justifies. " +
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
      "\n\nThe host gate did not report this round: its runner exited without a result or it timed out. Run `" + args.gate + "` in your cwd. Set `gate` to `passed` or `failed` " +
      "and `head` to the output of `git rev-parse HEAD`. A failing gate is a blocking finding.";
  }
  return task;
}

const safeName = (s) => String(s).replace(/[^A-Za-z0-9._-]/g, "-");

// The label is capped so the basename stays under the 255-byte filename limit; the round suffix keeps it unique.
function withOutput(item, name) {
  if (args.taskDir) item.output = args.taskDir.replace(/[\\/]+$/, "") + "/" + safeName(label).slice(0, 160) + "-" + name + ".md";
  return item;
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
    // Explicit form of `gate`: report "on" puts the acceptance report in the schema-enforced
    // structured_output call, which coders do not skip the way they skip a fenced report block.
    acceptance: { level: "verified", verify: [{ id: "gate", command: args.gate, timeoutMs: gateTimeoutMs }], report: "on" },
    outputSchema: coderSchema,
  });
  if (args.coderModel) item.model = args.coderModel;
  withOutput(item, "r" + round + "-coder" + (gateFailure ? "-retry" : ""));
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
    withOutput(item, "r" + round + "-reviewer-" + i);
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
let failure = null;

function record(key, result) {
  runLog.push({ key, runId: result && result.runId ? result.runId : null, ok: !!(result && result.ok) });
}

function finish(finalState) {
  return { state: finalState, rounds, head, gateBy, blocking, nonBlocking, runs: runLog, failure };
}

function progress(phase) {
  if (!hasState) return Promise.resolve();
  return state.set(stateKey, { phase, rounds, head, gateBy, blocking: blocking.length, nonBlocking: nonBlocking.length, runs: runLog, failure });
}

function coderFailed(finalState, key, result) {
  failure = { key, runId: result.runId || null, error: failureText(result) };
  gateBy = null;
  return finalState;
}

let outcome = null;
while (outcome === null) {
  rounds++;
  const priorHead = head;
  const coderKey = rounds === 1 ? "code-1" : "fix-" + rounds;
  let [coded] = await launchCoder(coderKey, rounds, blocking, null);
  record(coderKey, coded);
  let gateCheck = false;
  if (runTimedOut(coded)) {
    outcome = coderFailed("coder-timeout", coderKey, coded);
    break;
  } else if (gateUnreported(coded)) {
    gateCheck = true;
  } else if (!coded.ok) {
    const retryKey = coderKey + "-retry";
    [coded] = await launchCoder(retryKey, rounds, blocking, failureText(coded));
    record(retryKey, coded);
    if (runTimedOut(coded)) {
      outcome = coderFailed("coder-timeout", retryKey, coded);
      break;
    } else if (gateUnreported(coded)) {
      gateCheck = true;
    } else if (!coded.ok) {
      outcome = coderFailed(GATE_FAILED.test(failureText(coded)) ? "gate-failed" : "coder-failed", retryKey, coded);
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
