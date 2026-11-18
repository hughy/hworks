---
name: review-fanout
description: Run a review-only pass over one or more targets (a PR worktree, a plan file, a directory), including the pre-push and pre-merge review. Use instead of hand-writing a review script; for a coder change and its review, use review-loop.
---

# review-fanout

A review pass with no writer: open PRs, a plan, a branch before you brief a fix, or the review before a push or merge. Every reviewer reads every target read-only, a few targets at a time, and the result holds each reviewer's findings plus one merged list per target. Use pi-subagents on pi or the Codex runner below. On other harnesses, run the reviewers by hand. A coder change plus its review is `review-loop` (`../review-loop/SKILL.md`).

The workflow is `../../workflows/review-fanout.js` and the args script is `../../scripts/review-range.py`, relative to this file. Pass both as absolute paths. To write args by hand or read a custom-schema result, read `references/args.md`.

## Run on Codex

Set `HWORKS_WORKFLOW_RUNTIME=codex` when building args with `review-range.py`. Keep args, `taskDir`, and redirected logs outside the reviewed worktree. If building args by hand, include a `reviewers` array such as `[{"agent":"reviewer"}]`. Use Codex model IDs in each reviewer's optional `model` field. A pinned target requires a clean checkout at the specified head. The runner verifies the checkout again after review.

```sh
node <hworks>/scripts/codex-workflow.mjs review-fanout "$TASK_DIR/args.json" \
  >"$TASK_DIR/verdict.json" 2>"$TASK_DIR/workflow.log"
```

Read `verdict.json` after exit. Exit 0 means a result exists. Check `ok` and the findings before recording review coverage. Codex supports review schemas with declared object properties, arrays, enums, and scalar types. See `../review-loop/SKILL.md` for model defaults and timeouts.

## Pre-push and pre-merge review

Before `gh pr create`, and before every push to a branch with an open PR (addressing feedback or tidying an open PR counts):

- The gate and the project's push gate, when it names one, pass on the head being pushed. Rerun both after any merge of the base into the branch.
- The pre-push review below runs, unless step 1 exits 3 or the push only syncs a reviewed branch with its base (`../../references/split-and-sync.md`).
- `../../scripts/review-pre-read.py <base> <head>` runs, and every surviving reference it lists is fixed or justified.

Quick effort skips the review, never the gates or the pre-read. Say in the reply which of these ran and their results.

Review runs once per commit. A clean review-loop with at least one reviewer, a pre-push review, and a pre-merge review each record the range they covered, and each later review covers only commits no review has covered.

1. Build the args: `../../scripts/review-range.py args "$TASK_DIR" <trunk> <effort> "<intent>" --label <pre-push|pre-merge>`. It pins the range to the current HEAD, applies the rubric in `../../references/review/`, and picks the effort's reviewers: none for quick, one for standard, two for exhaustive (the second on the `review2` slot, a different provider when the profile sets one). For a stacked PR, pass the PR's base branch as `<trunk>`. Exit 3 means nothing to review; ship only then.
2. Launch and read the result as in Steps below.
3. Fix verified defects through review-loop, which reviews and records the fix. A fix committed any other way needs another `args` pass.
4. Once nothing the review raised is open, run the `record` command `args` printed on stderr. It records the head the reviewers read, so commits that fix findings stay uncovered until a review reads them.

A rebase or base merge keeps coverage only when it replays a byte-identical diff, as after merging trunk once a squash-merged parent has landed. A sync with the base that touches the branch's files is recorded instead of reviewed, per `../../references/split-and-sync.md`.

## Steps

1. Prepare each target: a PR goes in its own worktree at its head commit; a plan file needs only a `cwd` that contains it. Each `base` and `head` must be a full SHA, never a ref.
2. Set `taskDir` to `$TASK_DIR`. On pi, launch with `subagent({ workflow: "<abs>/workflows/review-fanout.js", args: <json>, async: true })`. Append the workflow run id and the mission id (when the launch reports one, as `details.missionId` or a `Mission: <id>` line) to `$TASK_DIR/progress.md`. On Codex, use the runner above.
3. Wait for the completion notice and read the returned value (in the completion message, or `workflow.value` in the run's `status.json`).

## Result

- `ok` is false when any reviewer failed. A failed reviewer stays in its target's `reviewers` with `ok: false` and an `error`. Rerun that review or read its run by `runId`; never read a missing review as a clean one.
- Each target's `merged` lists each finding once, with `raisedBy` naming every reviewer that matched it. Start with findings both reviewers raised; one raised by a single reviewer still needs checking.
