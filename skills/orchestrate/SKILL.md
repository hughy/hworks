---
name: graph
description: Drive a set of work units (issues, tasks) to reviewed, gate-passing branches with local pi subagents, several at once, one branch worktree per unit, surviving session restarts without starting a second writer. The session is the coordinator; scripts/graph.py holds all state and safety decisions; each unit runs through the review-loop workflow. Use for the hughy-mode Long run route on pi when the work is a backlog of independent units, or for "/graph", "work through this milestone", "drive these issues".
---

# graph

The session is the coordinator. It decides what each unit needs, dispatches workflows, and reads results. `scripts/graph.py` keeps every fact that must survive a restart and makes every safety decision: which unit may launch, which worktree it owns, whether a result is accepted, and what to do after a restart. Each unit runs through `workflows/review-loop.js`. Read `../review-loop/SKILL.md` first; this skill does not repeat it.

Paths below are relative to this file: the CLI is `../../scripts/graph.py`, the workflow `../../workflows/review-loop.js`. Pass both as absolute paths. Needs pi with pi-subagents.

## Terms

- Unit: one item of work, one branch, one worktree. Its source fields come from `units.json`: `{id, title, priority?, blockedBy?, branch?, url?, body?, paths?, effort?, claimedBy?}`.
- Attempt: one dispatch of review-loop for a unit. `graph.py launch` creates it; the attempt's args file is fixed for life.
- Store: `$TASK_DIR/graph/<slug>/`, written only by `graph.py`. Never edit it by hand.
- Runs dir: where pi-subagents keeps async run directories, the parent of the "Retention-managed async directory" a launch prints (`$TMPDIR/pi-subagents-uid-<uid>/async-subagent-runs`).

## Start

1. Get the units. A source adapter writes `units.json`; for example a tracker report with a units output. Write it by hand for a short list. A unit without `paths` runs alone, with nothing else active; add `paths` only from evidence (the issue names the files, or the code makes the scope plain) and say which in `knowledge.md`.
2. `TASK_DIR=$(scripts/task-dir.sh <slug>)`, store `S=$TASK_DIR/graph/<slug>`.
3. `graph.py --store $S init --repo <coordinator checkout> --base <trunk> --worktrees <dir> --gate '<gate>' --effort <effort>`. The gate must be the repo's check command and should finish in seconds; see Known runtime defects. Add `--grant '<the user's exact words>'` only when the user granted push and draft PRs; that line in `standing.md` is the only authority to ship. Never write a grant yourself.
4. `graph.py --store $S import units.json`. Copy the file to `$S/inventory.json`: the frozen inventory the end predicate is checked against.
5. Create one mission for the program: `subagent({ action: "mission.create", cwd: <coordinator checkout>, mission: { title } })`. Record the id as a line in `standing.md` notes is not allowed (the CLI owns that file), so keep it in `$TASK_DIR/progress.md` with the store path.
5. Create one mission for the program: `subagent({ action: "mission.create", cwd: <coordinator checkout>, mission: { title } })`. Keep its id and the store path in `$TASK_DIR/progress.md`; `standing.md` belongs to the CLI.

## Launch

Pilot with a window of 1. Raise it to 3 only after one unit went from launch to an accepted record without hand repair.

For each id from `graph.py --store $S next --max <window> --json`:

1. `graph.py --store $S launch <id> --workflow <abs review-loop.js>` prints `{id, attempt, cwd, args_path, workflow}`. It writes the intent, creates or adopts the worktree, renders the brief, and writes the args file. Exit 3 means the unit is not launchable; read why from `status`.
2. Dispatch with the args file contents verbatim: `subagent({ workflow, cwd, args: <JSON of args_path>, async: true, missionId })`. Never rebuild args: a relaunch after a restart re-attaches running children only for identical script and args.
3. `graph.py --store $S bind <id> <attempt> <workflow run id>`.

Launch the whole window in one message: the launches, then the dispatches, then the binds.

## Drain

On every completion notice:

1. Record from the run's `status.json`, never from the notice preview, which truncates: `graph.py --store $S record <id> <attempt> <runs dir>/<run id>/status.json`. Record refuses while any writer for the attempt may still run; that is correct, wait for the next notice.
2. Act on the recorded state:
   - `clean`: the envelope matched the live branch head on a clean tree with every required reviewer. Read `nonBlocking`, including downgraded findings. With a grant: push the branch, `gh pr create --draft`, track it with the harness PR tracker if there is one, then `graph.py set <id> pr-open --reason <url>`. Without one, leave it clean.
   - `stale`: the branch moved or the tree is dirty after review. Find out who wrote there before anything else.
   - `unresolved`, `gate-failed`, `review-failed`: read the blocking findings and the run. Either fix the brief (edit the unit's `body` in units.json, re-import, put the lesson in `knowledge.md`) so the next attempt can succeed, or park it. `next` retries until the attempt cap, then parks.
   - `blocked`: the coder needs a decision. `graph.py set <id> parked --reason <question>` and add the question to `open-questions.md`.
3. `graph.py --store $S status`, then launch the next window in the same message.

Never review or fix a unit's code inline; that is a second writer. A unit's follow-up work is a new attempt or a new unit.

## Restart

After a reload, a new session, or any doubt:

1. `graph.py --store $S status` and `graph.py --store $S reconcile --runs-dir <runs dir> --json`.
2. Do exactly what each unit's action says:
   - `wait`: nothing; its completion notice may not reach this session, so reconcile again later.
   - `record`: record the printed file.
   - `relaunch-same-args`: dispatch the existing args file for that attempt, unchanged, with the same missionId, then `bind` the same attempt to the new run id.
   - `retry`: record the file, then the unit is eligible through `next`.
   - `hold`: launch nothing for it. Report the reason. Hold covers live or unknown writers, superseded controllers that may still write, and failed runs that left commits or structured output (possibly finished work: read the commits and the output before deciding).
3. Mission records are not evidence of liveness: after a reload they mark live children failed. Only `reconcile` decides.

## End

When the predicate holds, or nothing is launchable and nothing is live:

1. `graph.py status` for the final table; every parked unit with its reason.
2. Close the mission (`mission.close`).
3. Run `scripts/blockers.sh --since <start date>` and report the top classes.
4. Questions that evidence could not settle go last, with options and a recommendation.

## Rules

- One writer per worktree, ever. Only `graph.py` decides ownership; `hold` is final until evidence changes.
- No merges, no pushes to trunk, no history rewrites, no deleting worktrees or branches. Ship only under the grant.
- Do not raise the window while any unit is `hold`.
- Goal-mission idle notices did not fire in testing; completion notices drive the loop. Before ending a turn with live units, say which units are live and that `reconcile` resumes them.

## Known runtime defects

- A host gate longer than about five seconds can outlive the async runner, which exits without a result after the coder finished. review-loop then has reviewers run the gate (`gateBy: reviewers`). Prefer a fast gate.
- After a reload, the workflow script stops but its children keep running; relaunching with identical args re-attaches them.
