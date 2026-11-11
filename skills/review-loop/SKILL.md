---
name: review-loop
description: Run one coder change and its review to a verdict, with fix rounds until the review is clean or the round cap hits. Use for the coder plus review cycle in hughy-router Fix and Build; for review only, use review-fanout.
---

# review-loop

Use it when a hughy-router Fix or Build step is one `coder` run plus its review. It replaces a hand-written workflow per round. Use pi-subagents on pi or the Codex runner below. On other harnesses, run the cycle by hand.

For a review-only pass over one or more targets (PRs, plans) with no coder, use `review-fanout` (`../review-fanout/SKILL.md`).

Paths below are relative to this file: the workflow is `../../workflows/review-loop.js` and the args script is `../../scripts/review-loop-args.sh`. Pass both as absolute paths.

## Run on Codex

Use the same brief, effort, gate, and review ledger as below. Set `HWORKS_WORKFLOW_RUNTIME=codex` for the args script so it skips the pi model roster. Save its stdout to an args JSON file outside the target worktree, then run:

```sh
node <hworks>/scripts/codex-workflow.mjs review-loop "$TASK_DIR/args.json" \
  >"$TASK_DIR/verdict.json" 2>"$TASK_DIR/workflow.log"
```

Run from the worktree or supply it as `cwd` in the args. The worktree must be clean and reserved for this writer. Keep `taskDir` and any redirected logs outside it. Codex leaves changes for the host to stage and commit after a valid `done` response. The host stages all non-ignored changes, so the coder must leave only files intended for that commit. It then runs the gate and pins reviewers to the resulting commit. The gate must leave the tree clean. Reviewers use read-only commands. Use the host gate for tests that need to write build artifacts or caches.

The runner uses the configured Codex model. Set `HWORKS_CODEX_MODEL` to override it for all children, or set `coderModel` and `review2Model` in the args for individual roles. Use Codex model IDs. A quick run uses low reasoning for the coder. `childTimeoutMs` defaults to 30 minutes per child. A host gate timeout counts as a gate failure on Codex.

Wait for the process to exit before reading the verdict. Exit 0 means the runner wrote a result, and the result's `state` says whether the work passed. Keep logs in the task directory. A failed gate may leave a local commit because the host checks the committed SHA. On interruption or failure without a result, inspect the checkout before restarting. Exit 125 means cleanup could not be verified. Confirm all writers and gate processes have stopped before reusing the worktree.

## Steps

1. Write the brief (goal, effort, verify) to a file in `$TASK_DIR`. Every child reads it, so state facts from the worktree only. The coder reads only the principles `agents/coder.md` names and the ones the brief lists by absolute path, so list any other principle the change needs, with why (for example `~/dev/hworks/skills/principle-boundary-discipline/SKILL.md` for code that parses external input).
2. Pick the worktree: a branch checkout with a clean tree. The coder commits there; the loop never creates or deletes a worktree, and it runs one writer at a time.
3. Build the args: `scripts/review-loop-args.sh <brief> <gate> <base> <effort> <worktree> "$TASK_DIR"` (its header documents each argument and the effort mapping). It emits `<base>` as a SHA (the merge-base, or the furthest commit the task dir's review ledger covers), because a ref such as `HEAD` moves with the coder's commits and empties the review diff. When it warns on stderr (both reviewers on one model, or a session slot it cannot resolve), say so in the reply. Children save outputs to the task dir under the run's `label`, so pass a fresh `label` or dir per run, or a rerun overwrites them. Optional JSON fields: `maxRounds` (default 3), `label`, and `gateTimeoutMs` (default 2400000, 40 minutes, covering a typical heavy-slot queue wait plus a full gate; projects with longer gates set `GATE_TIMEOUT_MS=<ms>` before the script). The emitted `gate` runs through `scripts/heavy.py`, so gate runs queue for the host's heavy-job slots; time spent queueing counts toward `gateTimeoutMs`, and heavy.py says on stderr when it waited.
4. On pi, launch with `subagent({ workflow: "<abs>/workflows/review-loop.js", args: <json>, async: true })`. Every child runs in `args.cwd` (the worktree) with `worktree: false`, so the launch cwd can be another checkout. Append the workflow run id and the mission id (when the launch reports one, as `details.missionId` or a `Mission: <id>` line) to `$TASK_DIR/progress.md`. The mission record owns run state, receipts, and resume; `$TASK_DIR` owns briefs, decisions, friction, and progress notes. Do not copy run status into `progress.md` beyond those ids. On Codex, use the runner above.
5. After completion, read `state` from the returned value (on pi, in the completion message or `workflow.value` in `status.json`; on Codex, in `verdict.json`):
   - `clean`: the gate passed and the last review had no blocking findings. Weigh `nonBlocking` and `risks`, then, when the run had at least one reviewer, record the reviewed range so later reviews skip it: `scripts/review-range.py record "$TASK_DIR" <base ref> <args base> <result head> review-loop --cwd <worktree>`, with the same `<base ref>` given to the args script. A run with 0 reviewers (quick) records nothing: the gate is not a review. Continue to the next step of the route.
   - `unresolved`: `maxRounds` review rounds (the first review counts as one) left `blocking` open. Read each finding, then fix, dismiss with a reason, or re-brief.
   - `blocked`: the coder needs a decision. Read its summary in the run output.
   - `gate-failed`: two coder runs in a row failed, the second by a failing host gate (`Acceptance verification 'gate' failed`). A gate timeout or a runner exit without a result does not count; those go to the reviewers. Check `git log` for work the failed runs committed, then read the error before re-briefing.
   - `coder-timeout`: a coder run hit its run deadline (`Subagent timed out after <ms>ms.`). The loop stops at once, with no retry and no review, so the branch may hold partial or uncommitted work and no gate result. Inspect the run in `failure.runId` for the stalled tool, read `git status` and `git log`, then re-brief.
   - `coder-failed`: two coder runs in a row failed and the second failure was neither a gate failure nor a timeout. Read `failure.error` and the run before re-briefing.
   - `gate-unverified`: the host gate did not report, because the coder runner exited without a result (a runtime defect with host gates longer than about five seconds) or the gate ran past `gateTimeoutMs`, and there were no reviewers to run the gate. Run the gate yourself.
   - `review-failed`: a reviewer failed, returned no structured findings, or returned `ok` with no evidence in `checked` twice (the loop re-asks once with a fresh reviewer, key `review-<round>-<i>-reask`, and names each missing or empty field). Rerun the review by hand.

Fix rounds converge: after the first review, reviewers tag each finding `prior` (an earlier finding still unfixed), `regression` (introduced by the fix), or `new`. Only `prior` and `regression` findings block; a blocking `new` finding moves to `nonBlocking` with `downgraded: true`, and an untagged blocking finding still blocks. Read downgraded findings before shipping.

Keep process instructions (commit counts, pacing) out of the brief's acceptance criteria: reviewers judge the brief literally, and fix rounds add commits.

On pi, when a coder runner exits without a result after finishing (a known runtime defect with slow host gates), or the host gate times out after `gateTimeoutMs`, the loop skips the retry and each reviewer runs the gate and reports it. `gateBy` in the result says whether the host or the reviewers ran the last gate.

The result also carries `risks` (`[{round, risk}]`, every open risk a coder reported; reviewers are told to verify each, but read them even when a reviewer dismissed one), `rounds`, `head` (the coder's last reported commit), `runs` (key, runId, ok) for inspecting any child, `failure` (key, runId, exact error of the coder run that ended the loop, else null; `gateBy` is then null), and `stopReasons` (`[{reason, round, detail}]`, diagnostics that never stop the loop: `stuck-fixer` when a fix round made no new commit, `stalled-count` when blocking findings did not drop, `repeated-finding` for each `prior` finding still open, `review-rejected` with the fields a reviewer left missing or empty). Read `stopReasons` first on `unresolved` or `review-failed`. With mission state, each round writes a progress record under the key `review-loop` or `review-loop.<label>`.
