---
name: review-loop
description: Run one coder change and its review to a verdict as a single pi-subagents workflow. coder implements a brief under a gate, reviewers check the branch diff, and blocking findings go back to a fresh coder until the review is clean or the round cap hits. Use for the coder plus review cycle in hughy-mode Fix and Build.
---

# review-loop

Use it when a hughy-mode Fix or Build step is one `coder` run plus its review. It replaces a hand-written workflow per round. It needs pi with pi-subagents. On other harnesses, run the cycle by hand.

Paths below are relative to this file: the workflow is `../../workflows/review-loop.js` and the args script is `../../scripts/review-loop-args.sh`. Pass both as absolute paths.

## Steps

1. Write the brief (goal, effort, verify) to a file in `$TASK_DIR`. Every child reads it, so state facts from the worktree only.
2. Pick the worktree: a branch checkout with a clean tree. The coder commits there; the loop never creates or deletes a worktree, and it runs one writer at a time.
3. Build the args: `scripts/review-loop-args.sh <brief> <gate> <base> <effort>`. Effort sets reviewers: quick 0 (gate only), standard 1, exhaustive 2 with the second on the `review2` slot. It warns on stderr when `review2` matches the reviewer model; say so in the reply. Add `maxRounds` (default 3) or `label` to the JSON if needed.
4. Launch: `subagent({ workflow: "<abs>/workflows/review-loop.js", cwd: "<worktree>", args: <json>, async: true })`.
5. Act on the returned `state`:
   - `clean`: the gate passed and the last review had no blocking findings. Weigh `nonBlocking` and continue to the next step of the route.
   - `unresolved`: `maxRounds` fix rounds left `blocking` open. Read each finding, then fix, dismiss with a reason, or re-brief.
   - `blocked`: the coder needs a decision. Read its summary in the run output.
   - `gate-failed`: two coder runs in a row failed the gate. Read the failing run's error before re-briefing.
   - `review-failed`: a reviewer failed or returned no structured findings. Rerun the review by hand.

The result also carries `rounds`, `head` (the coder's last reported commit), and `runs` (key, runId, ok) for inspecting any child. With mission state, each round writes a progress record under the key `review-loop` or `review-loop.<label>`.

The workflow's unit tests run with `node --test workflows/*.test.js`.
