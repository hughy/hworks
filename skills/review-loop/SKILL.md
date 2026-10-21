---
name: review-loop
description: Run one coder change and its review to a verdict as one pi-subagents workflow, with fix rounds until the review is clean or the round cap hits. Use for the coder plus review cycle in hughy-router Fix and Build; for review only, use review-fanout.
---

# review-loop

Use it when a hughy-router Fix or Build step is one `coder` run plus its review. It replaces a hand-written workflow per round. It needs pi with pi-subagents. On other harnesses, run the cycle by hand.

For a review-only pass over one or more targets (PRs, plans) with no coder, use `review-fanout` (`../review-fanout/SKILL.md`).

Paths below are relative to this file: the workflow is `../../workflows/review-loop.js` and the args script is `../../scripts/review-loop-args.sh`. Pass both as absolute paths.

## Steps

1. Write the brief (goal, effort, verify) to a file in `$TASK_DIR`. Every child reads it, so state facts from the worktree only. The coder reads only the principles `agents/coder.md` names and the ones the brief lists by absolute path, so list any other principle the change needs, with why (for example `~/dev/hworks/skills/principle-boundary-discipline/SKILL.md` for code that parses external input).
2. Pick the worktree: a branch checkout with a clean tree. The coder commits there; the loop never creates or deletes a worktree, and it runs one writer at a time.
3. Build the args: `scripts/review-loop-args.sh <brief> <gate> <base> <effort> <worktree> "$TASK_DIR"` (its header documents each argument and the effort mapping). It emits `<base>` as a SHA (the merge-base, or the furthest commit the task dir's review ledger covers), because a ref such as `HEAD` moves with the coder's commits and empties the review diff. When it warns on stderr (both reviewers on one model, or a session slot it cannot resolve), say so in the reply. Children save outputs to the task dir under the run's `label`, so pass a fresh `label` or dir per run, or a rerun overwrites them. Optional JSON fields: `maxRounds` (default 3), `label`, and `gateTimeoutMs` (default 600000, also settable as `GATE_TIMEOUT_MS=<ms>` before the script).
4. Launch: `subagent({ workflow: "<abs>/workflows/review-loop.js", args: <json>, async: true })`. Every child runs in `args.cwd` (the worktree) with `worktree: false`, so the launch cwd can be another checkout. Append the workflow run id and the mission id (when the launch reports one, as `details.missionId` or a `Mission: <id>` line) to `$TASK_DIR/progress.md`. The mission record owns run state, receipts, and resume; `$TASK_DIR` owns briefs, decisions, friction, and progress notes. Do not copy run status into `progress.md` beyond those ids.
5. Wait for the completion notice, then read `state` from the workflow's returned value (in the completion message, or `workflow.value` in the run's `status.json`):
   - `clean`: the gate passed and the last review had no blocking findings. Weigh `nonBlocking` and `risks`, then, when the run had at least one reviewer, record the reviewed range so later reviews skip it: `scripts/review-range.py record "$TASK_DIR" <base ref> <args base> <result head> review-loop --cwd <worktree>`, with the same `<base ref>` given to the args script. A run with 0 reviewers (quick) records nothing: the gate is not a review. Continue to the next step of the route.
   - `unresolved`: `maxRounds` review rounds (the first review counts as one) left `blocking` open. Read each finding, then fix, dismiss with a reason, or re-brief.
   - `blocked`: the coder needs a decision. Read its summary in the run output.
   - `gate-failed`: two coder runs in a row failed, the second by a failing host gate (`Acceptance verification 'gate' failed`). A gate timeout or a runner exit without a result does not count; those go to the reviewers. Check `git log` for work the failed runs committed, then read the error before re-briefing.
   - `coder-timeout`: a coder run hit its run deadline (`Subagent timed out after <ms>ms.`). The loop stops at once, with no retry and no review, so the branch may hold partial or uncommitted work and no gate result. Inspect the run in `failure.runId` for the stalled tool, read `git status` and `git log`, then re-brief.
   - `coder-failed`: two coder runs in a row failed and the second failure was neither a gate failure nor a timeout. Read `failure.error` and the run before re-briefing.
   - `gate-unverified`: the host gate did not report, because the coder runner exited without a result (a runtime defect with host gates longer than about five seconds) or the gate ran past `gateTimeoutMs`, and there were no reviewers to run the gate. Run the gate yourself.
   - `review-failed`: a reviewer failed, returned no structured findings, or returned `ok` with no evidence in `checked` twice (the loop re-asks once with a fresh reviewer, key `review-<round>-<i>-reask`). Rerun the review by hand.

Fix rounds converge: after the first review, reviewers tag each finding `prior` (an earlier finding still unfixed), `regression` (introduced by the fix), or `new`. Only `prior` and `regression` findings block; a blocking `new` finding moves to `nonBlocking` with `downgraded: true`, and an untagged blocking finding still blocks. Read downgraded findings before shipping.

Keep process instructions (commit counts, pacing) out of the brief's acceptance criteria: reviewers judge the brief literally, and fix rounds add commits.

When a coder runner exits without a result after finishing (a known runtime defect with slow host gates), or the host gate times out after `gateTimeoutMs`, the loop skips the retry and each reviewer runs the gate and reports it; `gateBy` in the result says whether the host or the reviewers ran the last gate.

The result also carries `risks` (`[{round, risk}]`, every open risk a coder reported; reviewers are told to verify each, but read them even when a reviewer dismissed one), `rounds`, `head` (the coder's last reported commit), `runs` (key, runId, ok) for inspecting any child, and `failure` (key, runId, exact error of the coder run that ended the loop, else null; `gateBy` is then null). With mission state, each round writes a progress record under the key `review-loop` or `review-loop.<label>`.
