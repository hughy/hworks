---
name: hughy-router
description: Entry point for non-trivial engineering work. Routes a task to one of six routes (investigate, fix, build, measure, ship, long run). Each route starts from a goal, effort, and verify brief, with the hworks deltas applied. Use for /skill:hughy-router or /hughy-mode on in pi, $hughy-router in Codex, "do this rigorously", or any task with a check that can pass or fail.
---

# hughy-router

Before following a route, read the host adapter once per session: `../../adapters/pi.md` on pi, or `../../adapters/codex.md` on Codex. On pi, then read every file in `../../adapters/local/` if it exists (in a linked worktree without one, the main checkout's); local adapters map the generic terms below to this harness's tools and win where they conflict. On Claude Code, use native subagents for the roles below.

Skills named below live at `../<name>/SKILL.md`; read them by path, since the commands among them (`orchestrate`, `handoff`) are hidden from the catalog.

Principles live at `../../references/principles/<name>.md`. Read one in full only when a selected skill relies on it or the user names it. If a child must apply one its agent prompt does not name, include its absolute path and the applicable hworks overrides in its brief.

## Brief and effort

Every brief, to a child or to yourself, states three things the way you would tell a coworker:

1. Goal: the outcome, and the report or symptom behind it.
2. Effort: the level below and its phrase.
3. Verify: the gate command and what result proves the goal.

Add scope and forbidden lines only when a second writer shares the repo or an irreversible action is in reach. Children can report blockers to the parent (`contact_supervisor` on pi), so a brief does not need to anticipate every question.

The user sets effort with a word on the invocation ("quick", "exhaustive"); default to standard.

| Effort | Thinking | Reviewers | Timebox | Phrase in the brief |
|---|---|---|---|---|
| quick | `:low` suffix | 0 | minutes | "One pass; stop at the first working fix." |
| standard | agent default | 1 | under an hour | "Be sure of the cause before you change code." |
| exhaustive | `:high` suffix, `coder` on the `exhaustive` slot | 2, different providers | as long as it takes | "Spend what it takes; iterate until it holds up to review." |

The model suffixes and slots in the table are pi settings. `scripts/models.sh show` prints the active profile's per-call overrides. Under `inherit` every slot is the session model, so a second-provider review needs a profile that sets `review2`. If a slot's model is unavailable, pick the closest available model and say so. On Codex, follow the adapter's effort mapping.

## Routes

### Investigate

A read-only question. Narrow (one module, one function): read the code yourself and answer with citations. Subsystem or history: plan the slices, spawn 2-4 `explorer` runs, one slice or evidence source each, then one `synthesizer` over their outputs. "What could this break": `../../references/blast-radius.md`. Read a repository that is not checked out from a clone (shallow is fine) in a `mktemp -d` dir under `$TMPDIR`, never page it through the forge's contents API. No code change. If one follows, re-route.

Untangle, or what to refactor across a whole repo or subsystem: `references/untangle.md`, which verifies leads, plans fixes and units, and changes no code. Why a repo is shaped the way it is, or what to refactor in it: the agents' own decision log is one more evidence source. `../../scripts/blockers.sh --log --cwd-match <repo>` prints every recorded decision (question, choice, evidence, how to reverse, and whether the operator kept or reversed it) and every correction, by branch and task; add `--grep <path or topic>` for one area. Give it its own explorer slice, or read it yourself for a narrow question. Cite an entry by its task dir and question. A `reversed` verdict, a decision whose evidence the code no longer matches, or the same correction across tasks marks a candidate refactor; check each against the current code before proposing it.

### Fix

A reported defect. If failing tests already pin the behavior, brief `coder` with the failing test names, the gate, and a commit body that names the root cause. Otherwise brief `coder` with the symptom as reported, the effort, and verify: a test that reproduces the report and fails with the fix reverted, plus the gate. For a live symptom with no repro, or a captured profile or heap snapshot, the deliverable is a diagnosis.

### Build

Behavior-preserving reshape: `../../references/refactoring.md` (pin the contract before moving anything: extend the existing tests to catch what a mutant shows they miss, and add a characterization test only where none covers it). Settle a design decision that an observation could settle with a throwaway prototype instead of asking. Name the data shape and its organizing structure before delegating. Before delegating a change that adds a flag, config knob, request or response field, timer, guard, tool, script, module, or test file, look for precedent (the repo's own patterns, sibling and in-flight changes, library or harness tools) and give the brief a Mechanisms list: for each, whether the issue or acceptance criteria require it or the design chose it, and for a chosen one, what breaks without it and the precedent checked. Drop a chosen mechanism with no reason. A new script or module needs a reason it cannot extend or share an existing one. A test needs a reason the code's own run or dry run would not show the failure as fast; an acceptance criterion asking for tests of a one-off process does not count. The brief also decides one PR or a stack: keep one PR when production changes are small (roughly under 400 changed lines and 15 files, not counting tests, fixtures, generated files, lockfiles, or docs), when merging only part would leave trunk unsafe, incomplete, or failing, or when the user asked for one; otherwise plan 2 to 4 layers that each merge alone, in order, leaving trunk building and passing, with tests beside the code they cover and no logical change split across layers.

### Measure

For a one-off slowness or sustained improvement of one metric, every number passes `../../references/benchmark-checklist.md` before it is reported or acted on.

### Ship

Read PR check state from the PR-tracking tool and review threads from it plus the adapter's reader for full review-thread bodies; use raw `gh api` only for data they lack (job logs, review decision, head metadata). Scope a task out of a long session for a new session to own: `../handoff/SKILL.md`. Split a reviewed branch that is still too large, or sync a branch with its base: `references/split-and-sync.md`.

### Long run

"Run until done", "going to bed", a predicate to drive to, or a program planned by `references/untangle.md` (drive its exit predicate). State the exit condition as a checkable predicate first. Each iteration: smallest change the evidence justifies, verify against the predicate, commit if it advanced, undo it in place or with `git revert` if it did not. Fix mid-run blockers yourself in their own commits. Never relax the predicate. Continue through plateaus. Stop at a dead end and say so. At the end, run `scripts/blockers.sh --since <run start date>` and put the top classes in the reply; a class seen in two runs goes to `/skill:correct`.

Work that outlives one session goes to a multi-agent coordinator only when all hold: the harness has one (per-area worker threads, shared memory); the work runs for days with several concurrent writers; follow-ups must route to the thread that owns an area, or shared memory or default independent review is wanted; and several times the tokens of direct work is acceptable.

On pi without such a coordinator, `orchestrate` (`../orchestrate/SKILL.md`) is an experimental, opt-in route for a set of items (issue ids, a milestone, a label), independent or stacked as dependent PRs on unmerged parents, when the user asks for it or wants several driven at once: it keeps one writer per branch and survives a reload. Run it with window 1 until a pilot passes. A short sequential list stays a plain brief with review-loop, and dependencies that are not stackable code changes (a deploy, a decision) use the loop below.

On Codex, when the user asks for hworks orchestration, follow `../orchestrate/SKILL.md` with `init --runtime codex`. Run it with window 1 until the pilot passes.

Otherwise, run this loop across sessions with `$TASK_DIR/progress.md` (`scripts/task-dir.sh <slug>`) and git as the record: read both before resuming, and update progress.md at each commit. Plan a multi-PR program with an issue-planning skill when one is installed; otherwise draft the issues in the reply.

## Deltas

These apply on every route.

- Every spawn goes to `coder`, `reviewer`, `explorer`, or `synthesizer` per the host adapter. On pi, `scripts/models.sh` sets each role's model and switches the roster. Override `model` per call only for exhaustive effort, the hardest code changes, or a different provider for the second review.
- On pi, run a `coder` change and its review as one `review-loop` workflow (`../review-loop/SKILL.md`) instead of hand-writing a script per round.
- On Codex, use the adapter's interactive review steps for a coder change or a review-only pass. For review only, pin the existing base and head and skip the coder step.
- Every `coder` run carries a `gate` (tests, typecheck, or the repo's verify skill). The gate result is the verification. "Inconclusive" or a gate that did not run is not a pass; say which. Tests the gate skipped for a missing build tag or env var (an unset service URI) did not run. For a fix, the evidence also shows the new test failing with the fix reverted; `scripts/mutate.py` with a `rev` mutant produces it. Each mutant's `test` is the narrowest command that should kill it, not the full suite, and `--no-baseline` skips the unmutated run when the gate just passed on the same tree. A red commit in history is not required, and every commit passes the gate.
- Run any command you expect to take over 60 seconds (a mutation run, a full test suite, a build) in the background and do independent work while it runs: review the diff, draft the commit or PR text, start the next item.
- Review runs once per commit. Follow `review-fanout` (`../review-fanout/SKILL.md`) for the coverage ledger and use the host adapter for dispatch: a pre-push and a pre-merge pass each cover only commits no earlier review covered, and you ship only when the ledger reports nothing left to review. Weight findings both reviewers raised highest. When both reviewers use the same model, say so in the reply. Act on verified defects; dismiss the rest with a reason. Review and record the fix through the host's review loop.
- PRs open as drafts, with a Conventional Commits title, the `AGENTS.md` PR rules, and the repo's PR template, found with `scripts/pr-template.sh`. Use a PR-tracking tool for check and review state when the harness has one.
- Self-review gates every push to a PR, not only the first. Before `gh pr create` or any `git push` to a branch with an open PR: the gate, and the project's push gate when it names one (a slow suite such as integration tests, run once per push instead of every review round), pass on the head being pushed, and both rerun after any merge of the base into the branch; the pre-push review runs (none when HEAD already passed review, or when the push only syncs a reviewed branch with its base, per `references/split-and-sync.md`); and `scripts/review-pre-read.py <base> <head>` runs, with every surviving reference it lists fixed or justified. Quick effort skips the review, never the gate or the pre-read. Requests to audit, tidy, or address feedback on an open PR count as pushes. The reply names the gate and push gate results, the review verdict or that nothing new needed review, and the pre-read result, or which did not run.
- Prose and comments follow the global `AGENTS.md`. Write a skill, an agent prompt, or an `AGENTS.md` per `../writing-for-agents/SKILL.md`.
- The brief's scope, public compatibility requirements, Autonomy, and green-commit gates above override every principle. In particular, `fix-root-causes` does not authorize out-of-scope fixes, and `migrate-callers-then-delete-legacy-apis` applies only when no external compatibility is required.
- Questions, product calls, irreversible actions, and undoing work follow the Autonomy and Planning sections of `global/AGENTS.md`. Answer a behavior, timing, layout, or output question by running it.
- Briefs carry only facts from the child's checkout. A test count, a file name, or a line number observed elsewhere does not go in a brief. Say "find the failing tests" instead of naming the file. A wrong fact in a brief costs a supervisor round trip or a silent workaround.
- When asked whether to do something, answer with your real view. "No" and "this does not earn its place" are valid answers.

## Reply

What changed, for whom. How it was verified: the gate or repro command and its result. What was skipped and why. One open decision or next action, or stop.
