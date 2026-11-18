# Rules and what enforces them

When the operator corrects a mistake, add its rule here with what enforces it. A rule enforced by nothing is a repeat risk: fix it with code, a type, a check, or a test before adding more prose. `global/AGENTS.md` points here; keep the rule text itself there only when it must fire in every session without a skill read.

| Rule | Enforced by |
|---|---|
| In a long-running autonomous run (orchestrate, `--unattended`, subagent children), do not ask mid-task unless the operator asked for questions, or run git commands that destroy history or uncommitted work. | `extensions/autonomy.ts`; `extensions/autonomy.test.mts` |
| A gate or test in foreground bash must not die on the bash timeout. | `extensions/gate-timeout.ts` raises `timeout` to 1800 s for gate and test commands; `extensions/gate-timeout.test.mts` replays past timed-out commands |
| `subagent({ workflow: true })` needs a fence tagged `js workflow`. | `extensions/workflow-fence.ts`; `extensions/workflow-fence.test.mts` |
| Put new logic in the script or module that owns the job, or share one; do not split it across new files. | review-loop reviewers block an unjustified new file (`workflows/review-loop.js`, asserted in `workflows/review-loop.test.js`); `agents/coder.md` |
| Follow the repo's testing rules; do not add test-only production code unless those rules allow it, or tests for one-off processes, for scripts whose own run or dry run shows the failure as fast, or that duplicate coverage; do not commit one-off scripts or codemods. | `agents/reviewer.md` items 2 and 5 require repo-rule and test-only production code checks in review-loop and review-fanout; review-loop reviewers rule on every added file (`addedFiles`) and test (`addedTests`, citing an excluding repo rule or the mutant only that test catches); `workflows/review-loop.test.js` |
