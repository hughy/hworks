# Out of scope

Ideas hworks has judged against the Rationale in `README.md` and not taken, from outside skill collections and from its own reviews. pstack skills that hworks does not link live in `DIVERGENCE.md`, which `scripts/skill.sh` maintains.

- Watching: plausible, but no observed failure or measured gain yet. Each row names the evidence that would admit it. kaizen checks these rows every run; a row whose condition is met becomes a fix and leaves this file.
- Declined: judged and rejected. A later proposal that matches a row needs evidence the row did not have.

Add a row when you defer or decline an idea, and remove it when the idea lands or its reason stops holding. Record the source commit so a resync can diff what changed since.

## Watching

| idea | source | what it would add | admit when |
|---|---|---|---|
| Hard repro gate for Fix | mattpocock/skills `diagnosing-bugs` (49dd158) | No hypothesis before one command already run fails on the reported symptom; minimize the repro; 3-5 falsifiable hypotheses; tagged debug logs; "no correct seam" reported as a finding | `friction.md` rows show a fix shipped on a theory without a repro, in 3 sessions |
| Judgment rules move from `global/AGENTS.md` to the reviewer | mattpocock/skills `retro` (49dd158) | Review has the least context pressure, so rules only a reviewer needs leave the always-loaded file. `global/AGENTS.md` is the largest hworks baseline part: 4.0k tokens in 699 sessions, 44.8M token-turns (`kaizen-tokens.py`, 14 days to 2026-10-15) | A kaizen experiment runs a section with and without it and the coder's output does not change |
| Positive phrasing for rule files | mattpocock/skills `writing-for-agents` (49dd158) | Rewrite prohibitions in `global/AGENTS.md` as target behavior, on the claim that a prohibition primes the banned behavior | A run of the rewritten rules shows fewer violations than the current text |
| PR body Evidence and Merge Danger | mattpocock/skills `pr` (49dd158) | Before/after evidence and a one-way or two-way door call with blast radius in `skills/edit-prose/references/issues-prs.md` | Reviewers ask how a PR was verified or how risky it is, in 3 PRs |
| Wizard scripts for human-only steps | mattpocock/skills `wizard` (49dd158) | An interactive bash script for the irreversible or outside-the-machine steps Autonomy skips | The same skipped step is a multi-step manual procedure in 2 runs |
| Whole-change verdict | private skill collection (2026-10-17) | The reviewer ends with "worth it / questionable / not worth it" for the change as a whole | Agents keep adding unrequired mechanism after reviewer item 2 landed, in 3 sessions |
| Per-repo lessons file | private skill collection (2026-10-17) | A lessons file per repo, kept outside the repo, fed to coder and reviewer briefs | The same class of reviewer-caught defect recurs in one repo across 3 sessions in `friction.md` |
| Daily service health watch | private skill collection (2026-10-17) | A recurring check over the observability backend for a service's monitors | The operator owns a production service with monitors and asks for a recurring check |
| Cleanup scan to tracker | private skill collection (2026-10-17) | A cleanup scan files one tracker issue with subissues instead of opening PRs | The operator asks for it twice |

## Declined

### mattpocock/skills (49dd158, evaluated 2026-10-15)

`writing-for-agents` and `handoff` were adopted as `skills/writing-for-agents/` and `skills/handoff/`. The skills in Watching above are not repeated here.

| skill | reason |
|---|---|
| `grill-me`, `grill-with-docs`, `grilling` | Interview before work; Autonomy defers questions to the end. The parts that change runs already live in `global/AGENTS.md` Planning: facts are the agent's job, a recommendation first, one batched round |
| `domain-modeling` | Writes `GLOSSARY.md` and ADRs into repos hworks does not own; a team decision. `principle-model-the-domain` is excluded in `DIVERGENCE.md` for the same default behavior |
| `to-spec`, `to-tickets`, `triage`, `wayfinder`, `setup-matt-pocock-skills` | Issue-tracker workflows belong in an overlay repo, since hworks is public and tracker-neutral. `to-tickets`' expand-migrate-contract rule for wide refactors is worth carrying to an overlay planning skill |
| `implement`, `implement-spec` | `orchestrate` and `review-loop` cover them, with per-unit review, gates, and restart recovery |
| `tdd` | Needs the user to confirm test seams, which conflicts with Autonomy. hworks `tdd` plus the `mutate.py` revert check proves more. Its tautology anti-pattern is in `principle-test-behavior-not-implementation` |
| `code-review` | The `reviewer` agent checks intent first and diversity comes from models, not axes. The smell baseline is default model behavior. No observed failure |
| `research` | `explorer`, `synthesizer`, and `why` cover it |
| `prototype` | pstack's `prototype.md` playbook covers it: throwaway, variants behind a switcher, observation as the test |
| `ask-matt` | hughy-router is the router, and `kaizen-setup.py` reports stale references. Its phase-boundary tree (`/clear`, `/compact`, hand-off) is harness-specific |
| `retro` | kaizen, `/skill:correct`, and `friction.md` cover the retrospective. Its review-side split is in Watching |
| `wait-what` | Same job as `bro` |
| `teach` | Multi-session tutoring workspace; hworks `teach` explains a body of work, a different job |
| `to-questionnaire` | An operator-only flow with no change to agent runs |
| `codebase-design`, `improve-codebase-architecture` | `correct` (architecture first) and `how` cover the survey; the deep-module vocabulary is pretrained |
| `chief-of-staff`, `claude-handoff`, `loop-me`, `setup-ts-deep-modules`, `writing-beats`, `writing-fragments`, `writing-shape` | Unshipped upstream (`in-progress/`); covered by `orchestrate` or personal workflows outside hworks' scope |
| `git-guardrails-claude-code`, `migrate-to-shoehorn`, `scaffold-exercises`, `setup-pre-commit` | Frozen upstream (`misc/`). `extensions/autonomy.ts` covers the git guard on pi; the rest are project-specific setup |

### private skill collection (2026-10-17)

The split-and-sync procedure in `skills/hughy-router/references/split-and-sync.md` and reviewer items 1, 4, and 8 were adopted from it. The ideas in Watching above are not repeated here.

| idea | reason |
|---|---|
| PR orchestrator with a decision-queue coordinator and tracker intake | Covered by `orchestrate` and PR tracking; the decision queue conflicts with Autonomy |
| Per-run cost script | Covered by `kaizen-tokens.py` |
| GraphQL budget tracker | No rate-limit failures observed |
| Daily, weekly, and OKR recaps | Personal workflows outside hworks |
| Anti-slop and technical-writing skills | Covered by `edit-prose` and `global/AGENTS.md` Prose |
| Interview skill | Already declined |
| Setup wizard with a profile file | Covered by `install.sh` and `adapters/local/` |
