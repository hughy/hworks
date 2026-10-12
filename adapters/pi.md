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
| `AskQuestion`, "ask the user", "pause for approval" | record the question and your chosen default in `$TASK_DIR/open-questions.md`, keep going, and ask at the end of the final reply (`~/AGENTS.md`, Autonomy; `autonomy.ts` blocks `ask_user_question`) |
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

Give every `coder` run a `gate` (the test command, typecheck, or the repo's verify skill). The gate result is the verification. The agent's summary is a report. A gate that did not run is not a pass. Where a pstack skill or playbook asks for a failing-test commit before the fix, the child instead shows the test failing with the fix reverted; every commit passes the gate.

## Enabling more of pstack

`scripts/skill.sh enable <name>` links another pstack skill or principle into `skills/`. Playbooks need no enabling; reference them by path from `hughy-mode`.
