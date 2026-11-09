---
name: orchestrate
description: Experimental. Drive several work items to reviewed, gate-passing branches at once, one worktree each, stacking dependents on unmerged parents, surviving a reload.
disable-model-invocation: true
---

# orchestrate

This adapts pstack's orchestrate playbook (`../../pstack/skills/poteto-mode/playbooks/orchestrate.md`) to pi with pi-subagents. It keeps the playbook's standing orders, status derived at each drain, verdicts keyed to a head SHA, a rolling window, a one-unit pilot, and retry by failure mode then park. It replaces Cursor's Task tool, cloud agents, `gt`, and the bun store with local workflows, one branch worktree per unit, and `scripts/orchestrate.py`. Follow this file, not the playbook.

The session is the coordinator. It selects units, writes their briefs, dispatches workflows, reads results, and ships. `scripts/orchestrate.py` is bookkeeping over the pi-subagents runtime: it keeps what must survive a restart and refuses unsafe steps (a launch into a busy window or a foreign worktree, a result whose head moved, a relaunch that could start a second writer). Each unit runs through `workflows/review-loop.js`; read `../review-loop/SKILL.md` first. This skill does not repeat it, the runtime docs, or `global/AGENTS.md`.

Resolve hworks paths absolutely: `O=<hworks>/scripts/orchestrate.py`, `WF=<hworks>/workflows/review-loop.js`. Every command below takes `--store "$S"`.

## Scope

The user's prompt decides which items are worked on. Fetch only those, never a whole backlog. Units run independently, or stacked on one unmerged unit of this store (Stacks, below). Exclude, with a reason in the inventory:

- Items with an open blocker that is not a unit of this store, or that is not code (a deploy, a decision, another team's change). orchestrate.py launches a plain dependent only after its dependency is `merged` with a head that is an ancestor of base, which a squash merge never satisfies; a stacked dependent starts as soon as its parent is `clean` or `pr-open`.
- Follow-ups to an open PR that is not a unit of this store. A follow-up to a unit's PR is a new stacked unit on it; `pr-open` units themselves are not relaunched except to restack.
- Items already claimed: an open PR, a branch, or a worktree someone else owns, or assigned to or in progress by someone else in the tracker.

A unit without `paths` runs alone: it starts only when no other unit is live or accepted and unmerged, and once it is `clean`, `stale`, or `pr-open` it blocks every other launch, except units stacked on it, until `set <id> merged`. Give a pathless item its own program, or exclude it with that reason. Never mark a unit merged to free the scheduler. Add `paths` only from evidence (the issue names the files, or the code makes the scope plain) and note the evidence in `knowledge.md`.

## Files

`$S = $TASK_DIR/orchestrate/<slug>/` is written only by orchestrate.py, except `$S/outputs/<id>/a<attempt>/`: each launch passes it as the unit's `taskDir`, and the children save their outputs there, so a retry never overwrites an earlier attempt's outputs. The coordinator's own files live in `$TASK_DIR`:

- `units.json`: what Start imports; pass its absolute path.
- `progress.md`: store path, runs dir, mission id, window, the end predicate, and before every yield, the live units and the next check.
- `inventory.json`: the frozen inventory with each item's disposition (included, or excluded and why).
- `knowledge.md`: lessons for the coordinator. Children never read it; a lesson a coder needs goes into that unit's `body`.
- `open-questions.md`: per `global/AGENTS.md`.

The runs dir is where pi-subagents keeps async run directories, the parent of the "Retention-managed async directory" a launch prints.

## Start

1. `git fetch origin` in the coordinator checkout. Turn the prompt into a selection: explicit ids, or a query (label, milestone, project) with a limit. Fetch exactly those items from the tracker, with title, description, status, priority, blockers, and branch name. If the selection is a query, state the resolved ids before launching.
2. Check each item against Scope: blockers resolved or stackable, no open PR, branch, or worktree for it (`gh pr list`, `git branch -a`, `git worktree list`). Write `inventory.json`, then `units.json` for the included items: `[{id, title, priority?, blockedBy?, stack?, branch?, url?, body?, paths?, effort?, gate?, claimedBy?}]`. `body` is the item's description plus anything the coder needs, including the absolute path of any principle beyond `agents/coder.md`'s list (see `../review-loop/SKILL.md` step 1). Set `stack: true` on a unit to build it on its one unmerged `blockedBy` unit (Stacks).
   - A brief for a heuristic tool (a reporter, classifier, or detector whose output a person triages) states its accuracy contract: what the output is for, which errors matter (a silent drop that hides a finding outweighs a mislabel the reader can see), and that a rare input form handled imperfectly does not block unless it changes what the reader would act on. Without it, reviewers hold the tool to exact semantics and every edge case blocks.
3. Pick a worktrees dir nobody else uses. Branches default to `orchestrate/<id>`; a unit's `branch` overrides it.
4. `python3 $O --store "$S" init --repo <coordinator checkout> --base origin/<trunk> --worktrees <dir> --gate '<gate, e.g. scripts/check.sh>' --effort standard --max-attempts 2`.
   - Effort is `standard` or `exhaustive`; orchestrate.py refuses `quick`, which has no reviewer.
   - The gate is the repo's full check: one command that runs every test suite, such as `scripts/check.sh` in hworks. Do not drop checks to make it fast; run the suites in parallel instead. See Known runtime defects.
   - Add `--grant '<the user's exact words>'` only when the user granted push and draft PRs. The `Authority granted` line in `$S/standing.md` is the only authority to ship, and orchestrate.py does not enforce it, so this skill does. To add a grant mid-program, rerun `init` with identical flags plus `--grant`. Never write a grant yourself.
5. `python3 $O --store "$S" import $TASK_DIR/units.json`. Import adds or updates the units in the file and keeps the rest. To add items later, repeat steps 1 and 2 for them, add them to `inventory.json` (the predicate then covers the new set), and import a file holding only the new units. To repair one unit's brief, import a file holding only that unit, with its other fields unchanged.
6. Create one mission: `subagent({ action: "mission.create", cwd: <coordinator checkout>, mission: { title } })`.
7. Write `progress.md`, including the end predicate. On the frozen inventory: every unit is `clean` (or `pr-open` under a grant), `parked` with a reason, or excluded with a reason; at least one `clean` or `pr-open` unit still has a receipt head equal to its live branch head on a clean tree (`status` re-derives `stale` otherwise); every state change came from an orchestrate.py command; zero live or unknown writers; mission closed. No launchable work left with the predicate unmet is a stalled run, not success.

## Launch

Pilot with window 1. Raise it to 3 only after one unit went from launch to an accepted record with no hand repair, and never while any unit is on `hold`.

For each id in `.selected` of `python3 $O --store "$S" next --max <window> --json` (`.refused` maps every other unit to the reason it is not launchable):

1. `python3 $O --store "$S" launch <id> --max <window> --workflow $WF` prints `{id, attempt, cwd, args_path, workflow}`.
   - Exit 3 with the store unchanged is a refusal; the reason is on stderr. Do not dispatch.
   - Exit 3 with `status` now showing `blocked` (dirty worktree, args script failure) spent the attempt. Fix the cause, then `set <id> queued --reason <fix>`.
   - A worktree path that exists from outside this store is refused. Pass `--adopt` only when you established it is unowned and its branch is the unit's.
2. Dispatch the args file contents verbatim: `subagent({ workflow: <workflow>, cwd: <cwd>, args: <args_path JSON>, async: true, missionId })`. Never rebuild args.
3. `python3 $O --store "$S" bind <id> <attempt> <workflow run id>`.

If dispatch returns an error, the launch outcome is uncertain. Run `reconcile`; it reports any run started with the attempt's args, live or ended. Bind what it names. After two failed dispatches with no run found, `set <id> parked --reason <error>`.

## Drain

On every completion notice:

1. If the notice reports a failed or stopped run, go to Restart for that unit first: a failed run may have left finished work, and `reconcile` holds it for inspection where `record` would spend the attempt.
2. Otherwise record from the run's `status.json`, never the notice preview: `python3 $O --store "$S" record <id> <attempt> <runs dir>/<run id>/status.json`. If record refuses (a writer may be alive, or the run is not the bound one), go to Restart. Do not wait for another notice; one may never come.
3. Act on the recorded state:
   - `clean`: read `nonBlocking`, including downgraded findings; they can hold real defects. Treat each entry of `risks` (open risks the coder reported) like a `nonBlocking` finding: verify it in the worktree, then act on it or record why not. Below the attempt cap, act on the worthwhile ones: verify each in the worktree, add them to the unit's `body`, re-import, `set <id> queued --reason <findings>`, and relaunch. At the cap, record each remaining one with a reason in `knowledge.md`. Ship under the grant (below); without one, leave it clean.
   - `stale`: the branch moved or the tree changed after review. When the reason starts with `stack parent`, restack instead (Stacks). Otherwise find out who wrote there first. When `status` derived `stale` for a unit stored `clean` or `pr-open`, a known writer made the new commits (a formatter, or a pre-push fix through review-loop), and the review ledger covers them, run `advance <id> --task-dir <dir> --reason <writer>` instead of requeueing or reporting; it keeps the unit `clean` or `pr-open` at the new head. `advance` refuses a unit that `record` stored as `stale`, since that state also means a required reviewer did not return ok. Otherwise `set <id> queued --reason <cause>` for a fresh attempt (commits stay; the next review covers them), or park. A `pr-open` unit that turns `stale` for any other reason has an open PR that no longer matches the reviewed head: report it and who wrote there, do not requeue it, and do not count it toward the predicate.
   - `unresolved`, `gate-failed`, `review-failed`: read the blocking findings. If record already parked it at the attempt cap, leave it parked. If the brief was wrong or thin, edit only that unit's `body` (keep its acceptance; add the surviving findings), re-import, and let `next` retry it. Otherwise park it. Do not reset the attempt cap by requeueing.
     - If the fix rounds keep regressing the same area (each fix breaks a neighbouring case of the same mechanism), the same approach will not converge. Rewrite the brief around a design that removes the mechanism and name the regression chain in the body.
   - `coder-timeout`, `coder-failed`: the coder run hit its deadline or failed without a gate failure; `next` does not retry these. The reason names the failed run, its error, and the unreviewed branch head. If record already parked it at the attempt cap, leave it parked. Otherwise inspect that run and the worktree, edit the unit's `body` (split it, or name the stalled command), re-import, and `set <id> queued --reason <cause>`; or park it.
   - `blocked`: `set <id> parked --reason <question>` and add the question to `open-questions.md` with state `asked`. After the answer, set its verdict per `global/AGENTS.md`, add it to the body, re-import, and `set <id> queued --reason <answer>`.
4. `python3 $O --store "$S" status`, then launch the next window in the same message.

Ship one clean unit:

1. Confirm the `Authority granted` line in `$S/standing.md`.
2. Run `status` and require the unit still `clean`.
3. Check the remote for the branch and for an existing PR; never repeat an external action that already happened.
4. From the unit worktree: `git push -u origin <branch>`, then `gh pr create --draft --base <trunk> --head <branch>` with the unit's title and a body per the repo template. A stacked unit whose parent is unmerged uses `--base <parent branch>` and follows Stacks. Find the template with `scripts/pr-template.sh` run in the worktree; never guess its filename, which may be lowercase or live in `docs/` or a `PULL_REQUEST_TEMPLATE/` directory. Pass the body with `--body-file`. When the PR already exists (a restacked or re-reviewed unit), push and skip `gh pr create`.
5. Run `gh pr checks <n>` once, without `--watch`. A pending or failing policy check whose description names missing PR-body fields means fix the body now; a tracker may show only that a policy gate blocks.
6. Track the PR with the harness PR tracker if there is one. `set <id> pr-open --reason <url>` and write the URL to `progress.md`.

The coordinator never edits a unit's code or reviews it in place of the workflow. Reading a worktree, a run, or a diff to decide what to do is fine.

## Stacks

A stacked unit lets work continue on a feature before its parent PR merges. It keeps one parent: `stack: true` plus exactly one unmerged `blockedBy` unit; every other dependency must be merged into base. orchestrate.py enforces this:

- `next` offers the child once the parent is `clean` or `pr-open` and not stale. `launch` branches the child from the parent's branch head and hands review-loop that head as the review base, so reviewers read only the child's commits while the gate runs on the whole stack. A unit and its stack ancestors or descendants hold no paths against each other; siblings still do.
- `status` derives `stale` with a `stack parent ...` reason when the parent's branch moved past what the child contains (a parent re-review, an `advance` for PR fixes), or when the parent merged without the child holding it in base (a squash merge, or a parent that moved before it merged). Drift propagates: a unit whose parent needs a restack is stale too, and nothing launches on it. A merged parent frees the child even though a squash-merged head never reaches base.
- Restack: `set <id> queued --reason restack`, then launch as usual once `next` offers it (the parent must be accepted again). Launch merges the parent's head, or base once the parent merged, into the child branch as a new commit and tells the coder to run the gate first. No rebase and no force push, so a child with an open PR takes a plain push. A conflicting merge is aborted and the launch blocks: park the unit and add the conflict to `open-questions.md` with state `asked`; once the operator commits the merge in the worktree, `set <id> queued`. Restacks spend attempts like any relaunch.
- Window: the child counts against the window like any unit. Launch children only after the pilot, and keep a stack short; each restack reruns the child's review.

Ship a stack bottom-up under the grant:

1. Ship a child only when its parent is `pr-open` or `merged`. Create the child PR with `--base <parent branch>` (or `<trunk>` once the parent merged).
2. Join the stack per `global/AGENTS.md`, Pull Requests: `gh stack init --base <trunk> <bottom branch> ... <top branch>` once from the coordinator checkout, then `gh stack link --base <trunk> <bottom branch> ... <top branch>`. Check each base with `gh pr view <n> --json baseRefName` and fix a mismatch with `gh pr edit <n> --base <branch>`. Write the stack number to `progress.md`.
3. When the user merges the parent (a PR tracker wake), `git fetch origin`, then `set <parent> merged --reason <url>`. Retarget the child PR to trunk if GitHub did not, then restack the child if `status` calls it stale. Never run `gh stack merge`, raw `git rebase`, or a force push on stack branches; the user lands the stack.

## Restart

After a reload, a new session, a refused record, a failed run, or any doubt:

1. `python3 $O --store "$S" status` and `python3 $O --store "$S" reconcile --runs-dir <runs dir> --json`.
2. Do what each unit's action says:
   - `wait`: a writer is live. After a reload this includes children whose workflow script stopped; they finish on their own, and the workflow does not resume. Their notice may not reach this session; check again before yielding.
   - `record`: record the printed file.
   - `relaunch-same-args`: nothing was dispatched for the attempt. Dispatch the existing args file unchanged with the same missionId, then `bind` the attempt to the new run id. orchestrate.py never returns this while any writer for the unit is alive.
   - `retry`: record the printed file. Below the attempt cap the unit becomes eligible through `next`; at the cap it is parked, so leave it parked.
   - `hold`: launch nothing for that unit. If the reason names a run to bind, bind it. If a failed or stopped run left commits or structured output (a workflow cut off by a reload ends this way), read both, then record the bound run's `<runs dir>/<run id>/status.json`. Below the attempt cap the unit becomes `run-failed` and `next` retries it from the branch, with a brief that tells the coder to read `git log` first; at the cap, record parks it. Otherwise report it.
3. Mission records do not show liveness; after a reload they mark live children failed. Only `reconcile` decides.

Before ending any turn with live units, write them and the next check to `progress.md`, and say in the reply which units are live and that `reconcile` resumes them. Goal-mission idle notices did not fire in testing, so a run is attended: someone starts the next turn.

The first pilot passes only if it also survives one reload while a coder runs: `reconcile` then answers `wait` or `hold` for that unit, never a second writer, and the unit later reaches an accepted record or a reasoned park. A workflow cut off by a reload never returns a result, so that attempt ends `run-failed`: plan the reload on attempt 1.

## Question a unit

`status` shows each unit's run ids. Tail a live child with `subagent({ action: "status", id, view: "transcript" })` and guide it with `steer`. Question a finished coder or reviewer with `subagent({ action: "resume", id: <child run id>, message })`, and tell it to answer without editing files. Never resume a coder whose unit has a live writer.

## End

When the predicate holds, or nothing is launchable:

1. `reconcile`, and account for every launch: no unit `launching` or `running`, no live or unknown writer. Do not close the mission until this holds.
2. `status` for the final table, with every parked and excluded item and its reason.
3. Close the mission (`mission.close`).
4. Report per unit: attempts, review rounds, wall time, manual interventions, gate run by host or reviewers, and downgraded findings. Read token use from the run status files; mission totals stayed at zero in testing.
5. Run `<hworks>/scripts/blockers.sh --since <start date>` and report the top classes.
6. If any unit is `pr-open`, keep tracking the PRs here and print this line in the report for the user to run, so each later CI or review wake reads a short summary instead of every unit's history:

   ```text
   /compact Keep only what the open PRs need: each PR's number, URL, branch, base, worktree, and gate, the orchestrate store path, any gh stack number with its branch order, and open review threads and failing checks. Drop unit histories.
   ```
7. Questions evidence could not settle go last, with options and a recommendation.

Stopping early: launch nothing new and drain. Never kill a child to stop; a parked unit keeps its reservation until `reconcile` shows its writers terminal.

## Rules

- One writer per worktree. orchestrate.py refuses the unsafe launches it can see; it cannot see a writer outside its store, which is why worktrees start fresh.
- No merges into trunk, no pushes to trunk, no history rewrites, no deleting worktrees or branches. Ship only under the grant. The only merges into unit branches are the restack merges launch makes and a conflicting restack the operator resolves by hand.
- Cost is bounded by count, not tokens. With `--max-attempts 2` and review-loop's default three rounds, a unit runs at most 24 children at standard effort and 36 at exhaustive (a coder retry and a reviewer re-ask in every round), plus any requeued attempts. Keep the selection small until the pilot measured real cost.

## Known runtime defects

- A slow host gate can outlive the async runner; review-loop then has the reviewers run the gate (`gateBy: reviewers`; see `../review-loop/SKILL.md`).
- After a reload, the workflow script stops and its children keep running to the end. The runtime can re-attach them on an identical relaunch in some cases, but its conditions are narrow, so orchestrate.py waits for them instead.
- A coder child that reports "exited with code 0 before writing a result" has usually committed its work. Check `git log` and `git status` in the unit worktree before treating it as lost; the workflow continues and the reviewers run the gate.
