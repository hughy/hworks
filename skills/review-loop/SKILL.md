---
name: review-loop
description: Run one coder change and its review to a verdict as a single pi-subagents workflow. coder implements a brief under a gate, reviewers check the branch diff, and blocking findings go back to a fresh coder until the review is clean or the round cap hits. Use for the coder plus review cycle in hughy-router Fix and Build.
---

# review-loop

Use it when a hughy-router Fix or Build step is one `coder` run plus its review. It replaces a hand-written workflow per round. It needs pi with pi-subagents. On other harnesses, run the cycle by hand.

For a review-only pass over one or more targets (PRs, plans) with no coder, use `review-fanout` (`../review-fanout/SKILL.md`).

Paths below are relative to this file: the workflow is `../../workflows/review-loop.js` and the args script is `../../scripts/review-loop-args.sh`. Pass both as absolute paths.

## Steps

1. Write the brief (goal, effort, verify) to a file in `$TASK_DIR`. Every child reads it, so state facts from the worktree only.
2. Pick the worktree: a branch checkout with a clean tree. The coder commits there; the loop never creates or deletes a worktree, and it runs one writer at a time.
3. Build the args: `scripts/review-loop-args.sh <brief> <gate> <base> <effort> <worktree> "$TASK_DIR"`. The script resolves `<base>` to the merge-base SHA of that ref and the worktree's HEAD; the workflow rejects anything but a SHA, because a ref such as `HEAD` moves with the coder's commits and empties the review diff. Effort sets the coder model and reviewers: quick runs the coder at `:low` with 0 reviewers (gate only); standard runs the coder role default with 1; exhaustive runs the coder on the `exhaustive` slot with 2, the second on the `review2` slot. A slot set to the session model resolves from `PI_PROVIDER` and `PI_MODEL`. The script warns on stderr when both reviewers run one model or a session slot cannot be resolved; say so in the reply. The task dir is emitted as `taskDir`: each child then saves its output to its own file there, `<label>-r<round>-coder.md` (`-coder-retry.md` for a retry) and `<label>-r<round>-reviewer-<n>.md`. Without it, children get no `output` path. Rerunning with the same task dir and label overwrites the earlier outputs, so pass a fresh `label` or dir per run. Add `maxRounds` (default 3) or `label` to the JSON if needed. `gateTimeoutMs` (default 600000, a positive integer) caps each host gate run; set it with `GATE_TIMEOUT_MS=<ms>` before the script, or add it to the JSON.
4. Launch: `subagent({ workflow: "<abs>/workflows/review-loop.js", args: <json>, async: true })`. Every child runs in `args.cwd` (the worktree) with `worktree: false`, so the launch cwd can be another checkout. Append the workflow run id and the mission id (when the launch reports one, as `details.missionId` or a `Mission: <id>` line) to `$TASK_DIR/progress.md`. The mission record owns run state, receipts, and resume; `$TASK_DIR` owns briefs, decisions, friction, and progress notes. Do not copy run status into `progress.md` beyond those ids.
5. Wait for the completion notice, then read `state` from the workflow's returned value (in the completion message, or `workflow.value` in the run's `status.json`):
   - `clean`: the gate passed and the last review had no blocking findings. Weigh `nonBlocking`, then, when the run had at least one reviewer, record the reviewed range so later reviews skip it: `scripts/review-range.py record "$TASK_DIR" <base ref> <args base> <result head> review-loop --cwd <worktree>`, with the same `<base ref>` given to the args script. A run with 0 reviewers (quick) records nothing: the gate is not a review. Continue to the next step of the route.
   - `unresolved`: `maxRounds` review rounds (the first review counts as one) left `blocking` open. Read each finding, then fix, dismiss with a reason, or re-brief.
   - `blocked`: the coder needs a decision. Read its summary in the run output.
   - `gate-failed`: two coder runs in a row failed, by a failing gate or a run that ended without finishing. A gate timeout or a runner exit without a result does not count; those go to the reviewers. Check `git log` for work the failed runs committed, then read the error before re-briefing.
   - `gate-unverified`: the host gate did not report, because the coder runner exited without a result (a runtime defect with host gates longer than about five seconds) or the gate ran past `gateTimeoutMs`, and there were no reviewers to run the gate. Run the gate yourself.
   - `review-failed`: a reviewer failed or returned no structured findings. Rerun the review by hand.

Fix rounds converge: after the first review, reviewers tag each finding `prior` (an earlier finding still unfixed), `regression` (introduced by the fix), or `new`. Only `prior` and `regression` findings block; a blocking `new` finding moves to `nonBlocking` with `downgraded: true`, and an untagged blocking finding still blocks. Read downgraded findings before shipping.

Keep process instructions (commit counts, pacing) out of the brief's acceptance criteria: reviewers judge the brief literally, and fix rounds add commits.

When a coder runner exits without a result after finishing (a known runtime defect with slow host gates), or the host gate times out after `gateTimeoutMs`, the loop skips the retry and each reviewer runs the gate and reports it; `gateBy` in the result says whether the host or the reviewers ran the last gate.

The result also carries `rounds`, `head` (the coder's last reported commit), and `runs` (key, runId, ok) for inspecting any child. With mission state, each round writes a progress record under the key `review-loop` or `review-loop.<label>`.

The workflow's unit tests run with `node --test workflows/*.test.js`.
