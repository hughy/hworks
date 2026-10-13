---
name: review-fanout
description: Run a review-only pass over one or more targets (a PR checked out in its own worktree, a plan file, a directory) as a single pi-subagents workflow. Every reviewer reviews every target read-only, a few targets at a time, and the result lists each reviewer's structured findings plus one merged list per target. Use instead of hand-writing a review script; for a coder change and its review, use review-loop.
---

# review-fanout

Use it for a review pass with no writer: reviewing open PRs, a plan, or a branch before you brief a fix. It replaces the hand-written script that builds one task per target, runs two reviewers on different models, batches the targets, and collects findings. It needs pi with pi-subagents. On other harnesses, run the reviewers by hand.

A coder change plus its review is `review-loop` (`../review-loop/SKILL.md`), not this.

The workflow is `../../workflows/review-fanout.js`, relative to this file. Pass it as an absolute path.

## Args

```json
{
  "targets": [{ "key": "pr-12", "cwd": "/abs/worktree", "task": "what to review and why", "base": "<full SHA>" }],
  "reviewers": [{ "agent": "reviewer", "model": "provider/id", "label": "name" }],
  "review2Model": "provider/id",
  "task": "text prepended to every target task",
  "schema": { "type": "object" },
  "concurrency": 2,
  "label": "review-fanout"
}
```

- `targets` (required, non-empty): `key` names the target in the result and in child keys (`<key>.r1`, `<key>.r2`); letters, digits, `.`, `_`, `-`, at most 120 characters, unique. `cwd` is the absolute path the reviewers run in. `task` states the intent and what to read. `base`, when given, must be a full commit SHA; the reviewers get `git diff <base>...HEAD`. A ref is rejected because it can move between launch and review, so two reviewers could read different diffs. Resolve one with `git -C <cwd> merge-base <ref> HEAD`.
- `reviewers`: each entry is `{agent?, model?, label?}`; `agent` defaults to `reviewer`, `model` to the agent's role model, and `label` to `<agent>-<n>`. Labels must be unique. When omitted, two reviewers run: `reviewer` on the role model, and `review2` on `review2Model`, which is then required. Take it from the `review2` slot in `scripts/models.sh show`; when that slot is the session model, pass `PI_PROVIDER/PI_MODEL`. Pick a model other than the reviewer role's, or both reviews run on one model.
- `task`: shared context, such as a rubric path or the review focus, prepended to each target's task.
- `schema`: replaces the default output schema. Without it, each reviewer returns `{summary, findings: [{severity, file, line?, claim, evidence, fix?}]}` with `severity` `blocking` or `non-blocking`.
- `concurrency` (default 2): targets reviewed at once. A batch launches every reviewer for each of its targets, so concurrency 2 with two reviewers runs four children. The next batch starts when the whole batch settles. A workflow run launches at most 64 children by default, so keep targets times reviewers within that, or pass a larger `maxSubagentSpawnsPerRun` on the launch.
- `label`: prefix for child labels in the fleet view.

Every reviewer child runs in its target's `cwd` with `worktree: false` and the schema as `outputSchema`. The task tells it to stay read-only; the `reviewer` agent has no edit tools.

## Steps

1. Prepare each target: a PR goes in its own worktree at its head commit; a plan file needs only a `cwd` that contains it. Resolve each `base` to a SHA.
2. Write the args JSON, then launch: `subagent({ workflow: "<abs>/workflows/review-fanout.js", args: <json>, async: true })`.
3. Wait for the completion notice and read the returned value (in the completion message, or `workflow.value` in the run's `status.json`).

## Result

```json
{
  "ok": false,
  "targets": [{
    "key": "pr-12",
    "reviewers": [
      { "label": "reviewer", "model": null, "ok": true, "runId": "...", "summary": "...", "findings": [] },
      { "label": "review2", "model": "provider/id", "ok": false, "runId": "...", "error": "..." }
    ],
    "merged": [{ "severity": "blocking", "file": "src/a.js", "line": 3, "claim": "...", "evidence": "...", "raisedBy": ["reviewer", "review2"] }]
  }]
}
```

- `ok` is false when any reviewer failed. A failed reviewer stays in its target's `reviewers` with `ok: false` and an `error`: the child failed, returned no structured output, or (default schema) returned no `findings` array. Rerun that review or read its run by `runId`; do not read a missing review as a clean one.
- `model` is `null` when the reviewer ran on its role model.
- `merged` lists each finding once. Two findings from different reviewers match when they name the same file (a leading `./` is ignored) and their claims share at least 80% of their words. The line does not decide a match, so two different defects on one line stay two entries, and one defect worded differently by two reviewers may also show up twice. The line only breaks ties: when a claim is open at several lines, a finding joins the entry on its own line, else the first one. The first reviewer's text is kept, `raisedBy` lists every reviewer that matched, and the severity is `blocking` if any of them said so. Findings from one reviewer never merge with each other. A finding raised by both reviewers is stronger evidence; one raised by a single reviewer still needs checking.
- With a custom `schema`, each reviewer entry carries its whole `structuredOutput`; `summary`, `findings`, and `merged` fill in only when the schema has those fields.

## Example

Review two open PRs, each checked out in its own worktree, plus a plan:

```json
{
  "task": "Apply the rubric at /abs/hworks/skills/interrogate/references/rubric.md.",
  "targets": [
    { "key": "pr-41", "cwd": "/abs/wt/pr-41", "base": "4f1c...40 hex", "task": "PR 41 adds retry with backoff to the fetch client. Check the retry bound and the tests." },
    { "key": "pr-42", "cwd": "/abs/wt/pr-42", "base": "9ab0...40 hex", "task": "PR 42 renames the config loader. Check every caller of the old name." },
    { "key": "plan", "cwd": "/abs/task-dir", "task": "Review plan.md: are the units independent, and does each have a check?" }
  ],
  "review2Model": "provider/second-model"
}
```

This runs `pr-41` and `pr-42` (four children) first, then `plan` (two). If `targets[1].reviewers[1].ok` is false, rerun that one review; otherwise act on each target's `merged` list, starting with findings both reviewers raised.

The workflow's unit tests run with `node --test workflows/*.test.js`.
