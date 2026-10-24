# Reading a pstack skill on pi

pstack was written for Cursor. When a skill under `pstack/skills/` names a Cursor mechanism, substitute the pi mechanism from this table. Nothing else in the skill changes.

| pstack says | On pi, do |
|---|---|
| `Task` tool, `subagent_type: generalPurpose` | `subagent` with `agent: explorer` (read-only exploration), `agent: reviewer` (adversarial review), or `agent: coder` (writes) |
| `subagent_type: "poteto-agent"` | `agent: coder` (alias resolves) |
| `subagent_type: "Comment Sicko"` | not available; the `no-comments` skill is not linked |
| `readonly: true` | pick a read-only agent (`explorer`, `reviewer`, `synthesizer`); their tool lists have no `edit` or `write` |
| `run_in_background: true` | `async: true` (the default); consume results at the barrier |
| `environment: "cloud"`, `cloud_base_branch` | run locally; use `worktree: true` for isolation |
| `model: <Cursor slug>`, slug-fallback paragraphs, `pstack-models.mdc` role lines | ignore; `scripts/models.sh` sets each role's model. Override per call only with a slot from `scripts/models.sh show`, or an available model when no slot fits |
| `AskQuestion`, "ask the user", "pause for approval" | record the question and your chosen default in `$TASK_DIR/open-questions.md`, keep going, and ask at the end of the final reply; large work with the operator present may get one up-front round in the reply text (`global/AGENTS.md`, Autonomy; `autonomy.ts` blocks `ask_user_question`) |
| `pstack/skills/poteto-mode/scripts/watch-pr/watch-pr`, `origin pr view --checks`, `origin pr thread list`, `gh api graphql` for review threads | the PR-tracking tool for check state and thread excerpts; the adapter's reader for full review-thread bodies |
| `/loop`, watcher heartbeat | `bg_wait`, or a background-process or PR-tracking tool when the harness has one |
| `agent-transcripts/`, `~/.cursor/projects/*/` | not available; skills that mine transcripts (`recall`, `reflect`, `automate-me`) are not linked |
| `/deslop`, `/no-comments`, `/unslop`, `/technical-writing`, `create-skill` | skip the step; the global `AGENTS.md` owns prose and comments |
| "open every PR ready, never as a draft" | open as a draft (`gh pr create --draft`) |
| `gt`, Graphite, Origin CLI | not used; stay on `gh` |

## Role to agent

| pstack role line | hworks agent |
|---|---|
| `how explorer`, `why investigators`, `swarm workers`, `arena runners` (cheap seats) | `explorer` |
| `how explainer`, `why synthesizer`, `arena cross-judge`, `judgment and prose` | `synthesizer` |
| `interrogate reviewers` | `reviewer`, two runs, the second on a different provider |
| `feature, refactoring`, `bug-fix`, `perf-issue`, `hillclimb` | `coder` |
| `hardest tasks` | `coder` with a per-call `model` override |

Model names live only in `models.conf`, `models.d/*.conf`, and the pi settings overrides that `scripts/models.sh` writes. `scripts/models.sh show` prints the active profile, each role's model, and its slots; `scripts/models.sh <profile>` applies a profile.

## Verification

Give every `coder` run a `gate` (the test command, typecheck, or the repo's verify skill). The gate result is the verification. The agent's summary is a report. A gate that did not run is not a pass, and tests it skipped for a missing build tag or env var did not run. Where a pstack skill or playbook asks for a failing-test commit before the fix, the child instead shows the test failing with the fix reverted; every commit passes the gate.

## Long commands

A child whose tools include both `bash` and `subagent_command` can monitor a long command: `bash({ command, yieldTimeMs: 30000 })` returns a handle with its `toolCallId`, then `subagent_command({ action: "status", toolCallId: "<that exact id>", waitMs: 30000 })` reports running or the terminal state, exit, and output tail. A yielded handle is not a successful exit, and the command still ends at its bash `timeout` (300 s when none is passed): `extensions/gate-timeout.ts` raises that to the 1800 s cap for gate and test commands, and any other long command needs an explicit `timeout`. The command stays owned by the child: it counts against the run's deadline, and the run fails if it ends with the command unfinished. A local adapter may name a different monitor.

## Workflow scripts

`subagent({ workflow: true })` runs the one fenced block tagged exactly `js workflow` in the same reply; to run a file, such as `workflows/review-loop.js`, pass its absolute path as `workflow`. `extensions/workflow-fence.ts` runs a reply's single untagged `js` block from a temp file and blocks other untagged shapes with this redirect.

## Enabling more of pstack

All pstack principles are linked into `skills/` for on-demand reference. Follow hughy-router's principle-loading policy and hworks overrides; availability does not add automatic triggers. `scripts/skill.sh enable <name>` links another pstack skill into `skills/`. Playbooks need no enabling; reference them by path from `hughy-router`.
