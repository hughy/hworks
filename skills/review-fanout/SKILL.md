---
name: review-fanout
description: Run a review-only pass over one or more targets (a PR worktree, a plan file, a directory) as one pi-subagents workflow, including the pre-push and pre-merge review. Use instead of hand-writing a review script; for a coder change and its review, use review-loop.
---

# review-fanout

A review pass with no writer: open PRs, a plan, a branch before you brief a fix, or the review before a push or merge. Every reviewer reads every target read-only, a few targets at a time, and the result holds each reviewer's findings plus one merged list per target. It needs pi with pi-subagents; on other harnesses, run the reviewers by hand. A coder change plus its review is `review-loop` (`../review-loop/SKILL.md`).

The workflow is `../../workflows/review-fanout.js`, relative to this file. Pass it as an absolute path. To write args by hand or read a custom-schema result, read `references/args.md`.

## Pre-push and pre-merge review

Review runs once per commit. A clean review-loop with at least one reviewer, a pre-push review, and a pre-merge review each record the range they covered, and each later review covers only commits no review has covered.

1. Build the args: `scripts/review-range.py args "$TASK_DIR" <trunk> <effort> "<intent>" --label <pre-push|pre-merge>`. It pins the range to the current HEAD, applies interrogate's rubric, and picks the effort's reviewers (the second on the `review2` slot). For a stacked PR, pass the PR's base branch as `<trunk>`. Exit 3 means nothing to review; ship only then.
2. Launch and read the result as in Steps below.
3. Fix verified defects through review-loop, which reviews and records the fix. A fix committed any other way needs another `args` pass.
4. Once nothing the review raised is open, run the `record` command `args` printed on stderr. It records the head the reviewers read, so commits that fix findings stay uncovered until a review reads them.

A rebase keeps coverage only when it replays a byte-identical diff, as after `gh stack rebase` onto a squash-merged parent. Any trunk change to a file the branch touches sends the branch back to review. `skills/hughy-router/SKILL.md` owns when this runs.

## Steps

1. Prepare each target: a PR goes in its own worktree at its head commit; a plan file needs only a `cwd` that contains it. Each `base` and `head` must be a full SHA, never a ref.
2. Set `taskDir` to `$TASK_DIR`, then launch: `subagent({ workflow: "<abs>/workflows/review-fanout.js", args: <json>, async: true })`. Append the workflow run id and the mission id (when the launch reports one, as `details.missionId` or a `Mission: <id>` line) to `$TASK_DIR/progress.md`, and nothing else about the run.
3. Wait for the completion notice and read the returned value (in the completion message, or `workflow.value` in the run's `status.json`).

## Result

- `ok` is false when any reviewer failed. A failed reviewer stays in its target's `reviewers` with `ok: false` and an `error`. Rerun that review or read its run by `runId`; never read a missing review as a clean one.
- Each target's `merged` lists each finding once, with `raisedBy` naming every reviewer that matched it. Start with findings both reviewers raised; one raised by a single reviewer still needs checking.
