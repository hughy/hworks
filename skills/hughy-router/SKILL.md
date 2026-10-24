---
name: hughy-router
description: Entry point for non-trivial engineering work. Routes a task to one of six routes (investigate, fix, build, measure, ship, long run). Each route starts from a goal, effort, and verify brief, with pstack playbooks as references and the hworks deltas applied. Use for /skill:hughy-router (one task) or /hughy-mode on (every turn), "do this rigorously", or any task with a check that can pass or fail.
---

# hughy-router

On pi, read `../../adapters/pi.md` once per session before following any playbook. It maps Cursor terms in pstack text to pi mechanisms and names the agent for each role. Then read every file in `../../adapters/local/` if it exists (in a linked worktree without one, the main checkout's); local adapters map the generic terms below to this harness's tools and win where they conflict. On Claude Code and Codex only the skills load: the roles named below map to that harness's own subagent, and `adapters/pi.md` does not apply.

Skills named below live at `../<name>/SKILL.md`; read them by path, since the commands among them (`orchestrate`, `handoff`) are hidden from the catalog. Playbooks live under `../../pstack/skills/poteto-mode/playbooks/`. Playbooks are references, not scripts. Read the matched one when a run stalls, the change is high-stakes, or it runs unattended, and apply the deltas below where they conflict. Do not copy its steps into a todo list.

All pstack principles are available at `../principle-<name>/SKILL.md`. Read a principle's leaf file in full only when a selected skill or playbook relies on it or the user names it; linking adds no automatic triggers. A reference that omits `principle-` uses the same path. If a child must apply one its agent prompt does not name, include the absolute leaf path and the applicable hworks overrides in its brief.

## Brief and effort

Every brief, to a child or to yourself, states three things the way you would tell a coworker:

1. Goal: the outcome, and the report or symptom behind it.
2. Effort: the level below and its phrase.
3. Verify: the gate command and what result proves the goal.

Add scope and forbidden lines only when a second writer shares the repo or an irreversible action is in reach. Children can ask through `contact_supervisor`, so a brief does not need to anticipate every question.

The user sets effort with a word on the invocation ("quick", "exhaustive"); default to standard.

| Effort | Thinking | Reviewers | Timebox | Phrase in the brief |
|---|---|---|---|---|
| quick | `:low` suffix | 0 | minutes | "One pass; stop at the first working fix." |
| standard | agent default | 1 | under an hour | "Be sure of the cause before you change code." |
| exhaustive | `:high` suffix, `coder` on the `exhaustive` slot | 2, different providers | as long as it takes | "Spend what it takes; iterate until it holds up to review." |

Effort does not decide `arena`; the design does (see Deltas).

Slots are per-call model overrides from the active profile. `scripts/models.sh show` prints them. Under the `inherit` profile every slot is the session model, so a second-provider review needs a profile that sets `review2`. If a slot's model is unavailable, pick the closest available model and say so.

## Routes

### Investigate

A read-only question. Narrow (one module, one function): read the code yourself and answer with citations. Subsystem or history: plan the slices with `how` and `why`, spawn 2-4 `explorer` runs, one slice or evidence source each, then one `synthesizer` over their outputs. The children do not load `how` or `why`, so each brief carries its slice and the absolute paths of the reference files it needs: `how/references/explorer-prompt.md` or `why/references/sources/<source>.md` for an explorer, `why/references/epistemics.md` for the synthesizer. "What could this break": the `blast-radius` skill. Playbook: `investigation.md`. Read a repository that is not checked out from a clone (shallow is fine) in a `mktemp -d` dir under `$TMPDIR`, never page it through the forge's contents API. No code change. If one follows, re-route.

### Fix

A reported defect. If failing tests already pin the behavior, brief `coder` with the failing test names, the gate, and a commit body that names the root cause. Otherwise brief `coder` with the symptom as reported, the effort, and verify: a test that reproduces the report and fails with the fix reverted, plus the gate. Live symptom with no repro: `runtime-forensics.md`. A captured profile or heap snapshot: `trace-forensics.md`. The deliverable of both forensics playbooks is a diagnosis.

### Build

New or changed behavior: `feature.md`. Behavior-preserving reshape: `refactoring.md` (pin the contract with a characterization test before moving anything). A design decision that an observation could settle: `prototype.md` instead of asking. Name the data shape and its organizing structure before delegating. Before delegating a change that adds a flag, config knob, request or response field, timer, guard, or tool, look for precedent (the repo's own patterns, sibling and in-flight changes, library or harness tools) and give the brief a Mechanisms list: for each, whether the issue or acceptance criteria require it or the design chose it, and for a chosen one, what breaks without it and the precedent checked. Drop a chosen mechanism with no reason. The brief also decides one PR or a stack: keep one PR when production changes are small (roughly under 400 changed lines and 15 files, not counting tests, fixtures, generated files, lockfiles, or docs), when merging only part would leave trunk unsafe, incomplete, or failing, or when the user asked for one; otherwise plan 2 to 4 layers that each merge alone, in order, leaving trunk building and passing, with tests beside the code they cover and no logical change split across layers.

### Measure

A one-off slowness: `perf-issue.md`. Sustained improvement of one metric: `hillclimb.md`. Every number passes the `benchmark-checklist` skill before it is reported or acted on.

### Ship

Open a PR: `opening-a-pr.md`. Drive a PR to merge-ready: `babysit.md`, with `../../pstack/skills/poteto-mode/references/bugbot-triage.md` for bot comments. Read PR check state from the PR-tracking tool and review threads from it plus the adapter's reader for full review-thread bodies; use raw `gh api` only for data they lack (job logs, review decision, head metadata). Land a verified stack: `shipping.md`. Resume or hand off: `session-pickup.md`, `pause-safely.md`. Scope a task out of a long session for a new session to own: `../handoff/SKILL.md`. Split a reviewed branch that is still too large, or sync a branch with its base: `references/split-and-sync.md`.

### Long run

"Run until done", "going to bed", a predicate to drive to. State the exit condition as a checkable predicate first. Each iteration: smallest change the evidence justifies, verify against the predicate, commit if it advanced, undo it in place or with `git revert` if it did not. Fix mid-run blockers yourself in their own commits. Never relax the predicate. Continue through plateaus. Stop at a dead end and say so. At the end, run `scripts/blockers.sh --since <run start date>` and put the top classes in the reply; a class seen in two runs goes to `/skill:correct`.

Work that outlives one session goes to a multi-agent coordinator only when all hold: the harness has one (per-area worker threads, shared memory); the work runs for days with several concurrent writers; follow-ups must route to the thread that owns an area, or shared memory or default independent review is wanted; and several times the tokens of direct work is acceptable.

On pi without such a coordinator, `orchestrate` (`../orchestrate/SKILL.md`) is an experimental, opt-in route for a set of independent items (issue ids, a milestone, a label) when the user asks for it or wants several driven at once: it keeps one writer per branch and survives a reload. Run it with window 1 until a pilot passes. A short sequential list stays a plain brief with review-loop, and work with dependencies uses the loop below.

Otherwise, and always on Claude Code and Codex, run this loop across sessions with `$TASK_DIR/progress.md` (`scripts/task-dir.sh <slug>`) and git as the record: read both before resuming, and update progress.md at each commit. Plan a multi-PR program with an issue-planning skill when one is installed; otherwise draft the issues in the reply.

## Deltas

These override the playbook text wherever they conflict.

- Any spawn a playbook describes goes to `coder`, `reviewer`, `explorer`, or `synthesizer` per `adapters/pi.md`. `scripts/models.sh` sets each role's model and switches the roster. Override `model` per call only for exhaustive effort, the hardest code changes, or a different provider for the second review.
- On pi, run a `coder` change and its review as one `review-loop` workflow (`../review-loop/SKILL.md`) instead of hand-writing a script per round.
- Every `coder` run carries a `gate` (tests, typecheck, or the repo's verify skill). The gate result is the verification. "Inconclusive" or a gate that did not run is not a pass; say which. Tests the gate skipped for a missing build tag or env var (an unset service URI) did not run. For a fix, the evidence also shows the new test failing with the fix reverted; `scripts/mutate.py` with a `rev` mutant produces it. Each mutant's `test` is the narrowest command that should kill it, not the full suite, and `--no-baseline` skips the unmutated run when the gate just passed on the same tree. A red commit in history is not required, and every commit passes the gate.
- Run any command you expect to take over 60 seconds (a mutation run, a full test suite, a build) in the background and do independent work while it runs: review the diff, draft the commit or PR text, start the next item.
- Run the `arena` skill only when the design is contested, crosses a public boundary, or has no precedent in the repo. Skip `architect`. One shape that follows the repo's existing pattern needs no bakeoff.
- Where a playbook requires `show-me-your-work`, keep its per-attempt log as a plain TSV in `$TASK_DIR` and skip the transcript audit and cross-model review. Where a playbook routes to `figure-it-out`, use an issue-planning skill when one is installed, or draft the issues in the reply.
- Review runs once per commit, through `review-fanout` (`../review-fanout/SKILL.md`), which owns the commands and the coverage ledger: a pre-push and a pre-merge pass each cover only commits no earlier review covered, and you ship only when it reports nothing left to review. Weight findings both reviewers raised highest. When `review2` matches `reviewer`, say so in the reply. Act on verified defects; dismiss the rest with a reason. Fix defects through review-loop, which reviews and records the fix.
- PRs open as drafts, with a Conventional Commits title, the `AGENTS.md` PR rules, and the repo's PR template, found with `scripts/pr-template.sh`. Use a PR-tracking tool instead of the watcher loop when the harness has one.
- Self-review gates every push to a PR, not only the first. Before `gh pr create` or any `git push` to a branch with an open PR: the gate, and the project's push gate when it names one (a slow suite such as integration tests, run once per push instead of every review round), pass on the head being pushed, and both rerun after any merge of the base into the branch; the pre-push review runs (none when HEAD already passed review); and `scripts/review-pre-read.py <base> <head>` runs, with every surviving reference it lists fixed or justified. Quick effort skips the review, never the gate or the pre-read. Requests to audit, tidy, or address feedback on an open PR count as pushes. The reply names the gate and push gate results, the review verdict or that nothing new needed review, and the pre-read result, or which did not run.
- Prose and comments follow the global `AGENTS.md`. Skip `/deslop`, `/no-comments`, `/unslop`, and `/technical-writing` steps. Where a playbook says to use `create-skill`, write the skill per `../writing-for-agents/SKILL.md`, which also covers agent prompts and `AGENTS.md`.
- Apply the linked principles (`explain-the-number`, `test-behavior-not-implementation`, `build-the-lever`, `encode-lessons-in-structure`, `attack-the-premise`, `separate-before-serializing-shared-state`, `sequence-verifiable-units`) when their trigger fires. Do not cite them in the reply.
- The brief's scope, public compatibility requirements, Autonomy, green-commit gates, and arena criteria above override every principle. In particular, `fix-root-causes` does not authorize out-of-scope fixes, `migrate-callers-then-delete-legacy-apis` applies only when no external compatibility is required, `outcome-oriented-execution` never permits a failing commit, and `exhaust-the-design-space` does not require a bakeoff outside the arena criteria.
- Questions, product calls, irreversible actions, and undoing work follow the Autonomy and Planning sections of `global/AGENTS.md`, including where a playbook says to ask, pause, revert, or discard. Answer a behavior, timing, layout, or output question by running it (`prototype.md`).
- Briefs carry only facts from the child's checkout. A test count, a file name, or a line number observed elsewhere does not go in a brief. Say "find the failing tests" instead of naming the file. A wrong fact in a brief costs a supervisor round trip or a silent workaround.
- When asked whether to do something, answer with your real view. "No" and "this does not earn its place" are valid answers.

## Reply

What changed, for whom. How it was verified: the gate or repro command and its result. What was skipped and why. One open decision or next action, or stop.
