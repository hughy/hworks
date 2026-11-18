# hworks on pi

review-loop, review-fanout, orchestrate, and the agent prompts name roles and generic steps. This file maps them to pi. Then read every file in `adapters/local/` if it exists (in a linked worktree without one, the main checkout's): local adapters map these terms to one harness's tools and win where they conflict.

| Step | On pi, do |
|---|---|
| Spawn a role | `subagent` with `agent: explorer` (read-only exploration), `reviewer` (adversarial review), `synthesizer` (judgment over explorer outputs), or `coder` (writes) |
| A read-only child | `explorer`, `reviewer`, or `synthesizer`; their tool lists have no `edit` or `write` |
| A background child | `async: true` (the default); consume results at the barrier |
| Isolation for a writer | `worktree: true` |
| A model for a role | `scripts/models.sh` sets each role's model. Override per call only with a slot from `scripts/models.sh show`, or an available model when no slot fits |
| A question for the operator | record the question and your chosen default in `$TASK_DIR/open-questions.md`, keep going, and ask at the end of the final reply; large work with the operator present may get one up-front round in the reply text (`global/AGENTS.md`, Autonomy; `autonomy.ts` blocks `ask_user_question` only in long-running autonomous runs: orchestrate, `--unattended`, and subagent children; in an interactive session, use `ask_user_question` for choices that are the operator's) |
| PR check state and review threads | the PR-tracking tool for check state and thread excerpts; the adapter's reader for full review-thread bodies |
| Waiting on a run | `bg_wait`, or a background-process or PR-tracking tool when the harness has one |

## Roles

| Work | Agent |
|---|---|
| One slice of an investigation | `explorer` |
| Judgment and prose over explorer outputs | `synthesizer` |
| Review | `reviewer`; exhaustive effort runs two, the second on a different provider |
| Feature, fix, refactor, performance | `coder` |
| The hardest changes | `coder` with a per-call `model` override |

Model names live only in `models.conf`, `models.d/*.conf`, and the pi settings overrides that `scripts/models.sh` writes. `scripts/models.sh show` prints the active profile, each role's model, and its slots; `scripts/models.sh <profile>` applies a profile.

## Verification

Give every `coder` run a `gate` (the test command, typecheck, or the repo's verify skill). The gate result is the verification. The agent's summary is a report. A gate that did not run is not a pass, and tests it skipped for a missing build tag or env var did not run. A fix shows its new test failing with the fix reverted instead of committing a failing test first; every commit passes the gate.

## Long commands

A child whose tools include both `bash` and `subagent_command` can monitor a long command: `bash({ command, yieldTimeMs: 30000 })` returns a handle with its `toolCallId`, then `subagent_command({ action: "status", toolCallId: "<that exact id>", waitMs: 30000 })` reports running or the terminal state, exit, and output tail. A yielded handle is not a successful exit, and the command still ends at its bash `timeout` (a harness guard may inject 300 s when none is passed): `extensions/gate-timeout.ts` raises that to 1800 s for gate and test commands, and any other long command needs an explicit `timeout`. The command stays owned by the child: it counts against the run's deadline, and the run fails if it ends with the command unfinished. A local adapter may name a different monitor.

## Workflow scripts

`subagent({ workflow: true })` runs the one fenced block tagged exactly `js workflow` in the same reply; to run a file, such as `workflows/review-loop.js`, pass its absolute path as `workflow`. `extensions/workflow-fence.ts` runs a reply's single untagged `js` block from a temp file and blocks other untagged shapes with this redirect.
