// Review-only passes: every reviewer reviews every target, a few targets at a time. Runs as a pi-subagents
// workflow script: a statement body with top-level await and the globals runs, args, state, emit, console.
// Each child runs read-only in its target's cwd; nothing is committed and no worktree is created.

const SHA = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i;
// Child keys are "<target key>.r<n>"; the runtime caps keys at 128 characters.
const TARGET_KEY = /^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/;
const ABSOLUTE = /^(?:\/|[A-Za-z]:[\\/])/;

function nonEmpty(value) {
  return typeof value === "string" && value.trim() !== "";
}

function isObject(value) {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

if (!Array.isArray(args.targets) || args.targets.length === 0) throw new Error("args.targets must be a non-empty array of {key, cwd, task, base?}");
const seenKeys = new Set();
args.targets.forEach((t, i) => {
  const at = "args.targets[" + i + "]";
  if (!isObject(t)) throw new Error(at + " must be an object {key, cwd, task, base?}");
  if (typeof t.key !== "string" || !TARGET_KEY.test(t.key)) throw new Error(at + ".key must be 1 to 120 letters, digits, '.', '_' or '-', starting with a letter or digit");
  if (seenKeys.has(t.key)) throw new Error("args.targets has duplicate key '" + t.key + "'");
  seenKeys.add(t.key);
  if (typeof t.cwd !== "string" || !ABSOLUTE.test(t.cwd)) throw new Error(at + ".cwd must be an absolute path (target '" + t.key + "')");
  if (!nonEmpty(t.task)) throw new Error(at + ".task must be a non-empty string (target '" + t.key + "')");
  // A ref such as main or HEAD moves between launch and review, so two reviewers could read different diffs.
  if (t.base !== undefined && (typeof t.base !== "string" || !SHA.test(t.base))) throw new Error(at + ".base must be a full commit SHA (40 or 64 hex chars), not a ref (target '" + t.key + "')");
});

if (args.review2Model !== undefined && !nonEmpty(args.review2Model)) throw new Error("args.review2Model must be a non-empty model id");
let reviewerSpecs = args.reviewers;
if (reviewerSpecs === undefined) {
  if (!nonEmpty(args.review2Model)) throw new Error("args.review2Model is required when args.reviewers is omitted: the default runs the reviewer role model and review2Model");
  reviewerSpecs = [{ agent: "reviewer", label: "reviewer" }, { agent: "reviewer", model: args.review2Model, label: "review2" }];
}
if (!Array.isArray(reviewerSpecs) || reviewerSpecs.length === 0) throw new Error("args.reviewers must be a non-empty array of {agent?, model?, label?}");
const reviewers = reviewerSpecs.map((r, i) => {
  const at = "args.reviewers[" + i + "]";
  if (!isObject(r)) throw new Error(at + " must be an object {agent?, model?, label?}");
  if (r.agent !== undefined && !nonEmpty(r.agent)) throw new Error(at + ".agent must be a non-empty agent name");
  if (r.model !== undefined && !nonEmpty(r.model)) throw new Error(at + ".model must be a non-empty model id");
  if (r.label !== undefined && !nonEmpty(r.label)) throw new Error(at + ".label must be a non-empty string");
  const agent = r.agent || "reviewer";
  return { agent, model: r.model || null, label: r.label || (agent + "-" + (i + 1)) };
});
const seenLabels = new Set();
for (const r of reviewers) {
  if (seenLabels.has(r.label)) throw new Error("args.reviewers has duplicate label '" + r.label + "'");
  seenLabels.add(r.label);
}

if (args.task !== undefined && typeof args.task !== "string") throw new Error("args.task must be a string");
if (args.schema !== undefined && !isObject(args.schema)) throw new Error("args.schema must be a JSON schema object");
const concurrency = args.concurrency === undefined ? 2 : args.concurrency;
if (!Number.isInteger(concurrency) || concurrency < 1) throw new Error("args.concurrency must be a positive integer");
if (args.label !== undefined && !nonEmpty(args.label)) throw new Error("args.label must be a non-empty string");
const label = args.label || "review-fanout";
if (args.taskDir !== undefined && (typeof args.taskDir !== "string" || !ABSOLUTE.test(args.taskDir))) throw new Error("args.taskDir must be an absolute path");

const defaultSchema = {
  type: "object",
  properties: {
    summary: { type: "string" },
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
          fix: { type: "string" },
        },
        required: ["severity", "file", "claim", "evidence"],
      },
    },
  },
  required: ["summary", "findings"],
};
const customSchema = args.schema !== undefined;
const schema = customSchema ? args.schema : defaultSchema;

function reviewTask(target) {
  const parts = [];
  if (nonEmpty(args.task)) parts.push(args.task.trim());
  parts.push(target.task.trim());
  let rules = "";
  if (target.base) rules += "Diff: run `git diff " + target.base + "...HEAD` in your cwd and read the surrounding code, not only the diff. ";
  rules +=
    "Verify every claim against the code before reporting it. " +
    "You are read-only: do not edit, commit, or stage anything.";
  if (!customSchema) {
    rules +=
      " Put a one-paragraph verdict in summary. Give each finding the file path relative to your cwd, the line when one applies, " +
      "the claim, the evidence you verified it with, and a fix when you have one. " +
      "Mark a finding blocking only when it is a verified defect or a gap against the stated intent. " +
      "Return an empty findings array when the target is sound.";
  }
  parts.push(rules);
  return parts.join("\n\n");
}

function childKey(target, index) {
  return target.key + ".r" + (index + 1);
}

function reviewItem(target, targetIndex, reviewer, index) {
  const item = {
    key: childKey(target, index),
    label: label + ": " + target.key + " " + reviewer.label,
    agent: reviewer.agent,
    task: reviewTask(target),
    cwd: target.cwd,
    // worktree: false overrides a global worktree default so the reviewer reads the target checkout itself.
    worktree: false,
    outputSchema: schema,
  };
  if (reviewer.model) item.model = reviewer.model;
  if (args.taskDir) {
    // Sanitized or truncated names can collide ("a b" and "a-b"), so the target and reviewer ordinals keep
    // each file unique. Each name part is capped so the basename stays under the 255-byte filename limit.
    const clean = (s) => s.replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 48);
    const name = clean(label) + "-t" + (targetIndex + 1) + "-r" + (index + 1) + "-" + clean(target.key) + "-" + clean(reviewer.label);
    item.output = args.taskDir.replace(/[\\/]+$/, "") + "/" + name + ".md";
  }
  return item;
}

function reviewerEntry(reviewer, result) {
  const entry = { label: reviewer.label, model: reviewer.model, ok: false, runId: result && result.runId ? result.runId : null };
  if (!result || !result.ok) {
    entry.error = String((result && (result.error || result.output)) || "reviewer failed without an error message");
    return entry;
  }
  const out = result.structuredOutput;
  // The runtime leaves structuredOutput undefined when none was captured; null can be schema-valid output.
  const missing = customSchema ? out === undefined : !isObject(out);
  if (missing) {
    entry.error = "reviewer returned no structured output";
    return entry;
  }
  if (!customSchema && !Array.isArray(out.findings)) {
    entry.error = "reviewer structured output has no findings array";
    return entry;
  }
  entry.ok = true;
  if (isObject(out) && typeof out.summary === "string") entry.summary = out.summary;
  if (isObject(out) && Array.isArray(out.findings)) entry.findings = out.findings.filter(isObject);
  if (customSchema) entry.structuredOutput = out;
  return entry;
}

function normalFile(file) {
  return typeof file === "string" ? file.trim().replace(/^(\.\/)+/, "") : "";
}

function claimWords(claim) {
  const words = String(claim || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  return new Set(words ? words.split(" ") : []);
}

// Near-identical: at least 80% word overlap (Jaccard) after lowercasing and dropping punctuation.
function sameClaim(a, b) {
  const wa = claimWords(a);
  const wb = claimWords(b);
  if (wa.size === 0 || wb.size === 0) return false;
  let shared = 0;
  for (const w of wa) if (wb.has(w)) shared++;
  return shared / (wa.size + wb.size - shared) >= 0.8;
}

// Claims must match even on the same line: a line match alone can join two different defects,
// and the second would vanish from merged.
function sameFinding(a, b) {
  return normalFile(a.file) === normalFile(b.file) && sameClaim(a.claim, b.claim);
}

function sameLine(a, b) {
  return a.line !== undefined && a.line !== null && a.line === b.line;
}

// A reviewer's own findings never merge with each other: two issues on one line stay two entries.
// When a claim is open at several lines, the same-line entry wins so raisedBy points at the right place.
function mergeFindings(entries) {
  const merged = [];
  for (const entry of entries) {
    for (const finding of entry.findings || []) {
      const open = merged.filter((m) => !m.raisedBy.includes(entry.label) && sameFinding(m, finding));
      const match = open.find((m) => sameLine(m, finding)) || open[0];
      if (!match) {
        merged.push(Object.assign({}, finding, { raisedBy: [entry.label] }));
        continue;
      }
      match.raisedBy.push(entry.label);
      if (finding.severity === "blocking") match.severity = "blocking";
    }
  }
  return merged;
}

const results = [];
let ok = true;
for (let start = 0; start < args.targets.length; start += concurrency) {
  const batch = args.targets.slice(start, start + concurrency);
  const items = [];
  batch.forEach((target, t) => reviewers.forEach((reviewer, i) => items.push(reviewItem(target, start + t, reviewer, i))));
  const settled = await runs.all(items);
  batch.forEach((target, t) => {
    const entries = reviewers.map((reviewer, i) => reviewerEntry(reviewer, settled[t * reviewers.length + i]));
    if (entries.some((e) => !e.ok)) ok = false;
    results.push({ key: target.key, reviewers: entries, merged: mergeFindings(entries) });
  });
}

return { ok, targets: results };
