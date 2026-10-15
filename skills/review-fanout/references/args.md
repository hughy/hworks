# review-fanout args and result

Read this when writing args by hand or reading a custom-schema result. `scripts/review-range.py args` builds args for the pre-push and pre-merge review.

## Args

```json
{
  "targets": [{ "key": "pr-12", "cwd": "/abs/worktree", "task": "what to review and why", "base": "<full SHA>" }],
  "reviewers": [{ "agent": "reviewer", "model": "provider/id", "label": "name" }],
  "review2Model": "provider/id",
  "task": "text prepended to every target task",
  "schema": { "type": "object" },
  "concurrency": 2,
  "label": "review-fanout",
  "taskDir": "/abs/task-dir"
}
```

- `targets` (required, non-empty): `key` names the target in the result and in child keys (`<key>.r1`, `<key>.r2`); letters, digits, `.`, `_`, `-`, at most 120 characters, unique. `cwd` is the absolute path the reviewers run in. `task` states the intent and what to read. `base`, when given, must be a full commit SHA; the reviewers get `git diff <base>...HEAD`. `head`, when given, needs `base` and must be a full commit SHA; the reviewers then get `git diff <base>...<head>` and read files at `<head>`, so moving the checkout during the review does not change what they read. Resolve a ref with `git -C <cwd> merge-base <ref> HEAD`.
- `reviewers`: each entry is `{agent?, model?, label?}`; `agent` defaults to `reviewer`, `model` to the agent's role model, and `label` to `<agent>-<n>`. Labels must be unique. When omitted, two reviewers run: `reviewer` on the role model, and `review2` on `review2Model`, which is then required. Take it from the `review2` slot in `scripts/models.sh show`; when that slot is the session model, pass `PI_PROVIDER/PI_MODEL`. Pick a model other than the reviewer role's, or both reviews run on one model.
- `task`: shared context, such as a rubric path or the review focus, prepended to each target's task.
- `schema`: replaces the default output schema, `{summary, findings: [{severity, file, line?, claim, evidence, fix?}]}` with `severity` `blocking` or `non-blocking`.
- `concurrency` (default 2): targets reviewed at once. A batch launches every reviewer for each of its targets, and the next batch starts when the whole batch settles. A workflow run launches at most 64 children by default, so keep targets times reviewers within that, or pass a larger `maxSubagentSpawnsPerRun` on the launch.
- `label`: prefix for child labels in the fleet view.
- `taskDir`: an absolute directory, usually `$TASK_DIR`. Each reviewer then saves its output to `<taskDir>/<label>-t<target n>-r<reviewer n>-<target key>-<reviewer label>.md`. Without it, reviewers get no `output` path. Rerunning with the same `taskDir` and `label` overwrites the earlier outputs, so pass a fresh `label` or dir per run.

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

- `model` is `null` when the reviewer ran on its role model.
- `merged` matching: two findings from different reviewers match when they name the same file (a leading `./` is ignored) and their claims share at least 80% of their words. The line does not decide a match, so two defects on one line stay two entries, and one defect worded differently may show up twice. The line only breaks ties between candidate entries. The first reviewer's text is kept, and the severity is `blocking` if any matching reviewer said so. Findings from one reviewer never merge with each other.
- With a custom `schema`, each reviewer entry carries its whole `structuredOutput`; `summary`, `findings`, and `merged` fill in only when the schema has those fields.

## Example

Two open PRs, each in its own worktree, plus a plan:

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

This runs `pr-41` and `pr-42` (four children) first, then `plan` (two).
