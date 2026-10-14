---
name: retro
description: Periodic retrospective over recent agent sessions. Runs scripts/retro-sessions.py (tooling agents keep rewriting) and scripts/blockers.sh (where runs blocked) over a window, verifies each finding in a few example sessions, and sends it to exactly one fix - a new tool built through orchestrate, a routing fix for an ignored tool, a correct pass for a repeated mistake, an upstream issue draft for a harness bug, or a guidance edit - and tracks each action until later sessions show it worked. Use for "/retro" or a request to turn recent session history into fixes; run every week or two.
---

# retro

Agents keep writing the same throwaway tools, hitting the same harness bugs, and asking the same questions. retro turns that history into fixes. Run it every week or two over the default 14-day window; a longer gap only makes the reports noisier.

Findings about how the operator prompts or works with agents belong to `hansei` (`../hansei/SKILL.md`), which hands its system findings to retro as prompts.

It keeps no state beyond its task dir: `TASK_DIR=$(<hworks>/scripts/task-dir.sh retro)`, run from the hworks checkout. Each run writes `findings-<YYYY-MM-DD>.md` there. Read the previous one first and, before triage, reconcile each action not yet `effective` or dropped against git, orchestrate records, and upstream drafts, then update its state (see Output). A reviewed branch or open PR has not landed. An upstream draft waiting for the user to file it is `awaiting-user`, not a failed fix.

A finding that comes back after its fix landed means the fix did not work, and goes to a higher level (see Triage). Count a recurrence only from examples dated after the fix landed: report windows overlap, so a window can still hold pre-fix events. A finding that merely drops below the triage thresholds is `unproven`, not `effective`; mark it `effective` only when sessions that exercised the fixed path show the problem is gone.

## Privacy

Transcripts hold private content: code, ticket text, tokens, names from every repo the agent touched. Both reporters print it (session paths, command samples, open-question text). Nothing from them goes into this repo: not in a commit, a skill, a test fixture, or a unit brief that a public branch will carry. Keep report output in `$TASK_DIR`. A fix written into hworks states the general rule, never the session it came from. A tool or rule specific to one employer goes to the private companion repo that `adapters/local/` names, when the user has one; without one, list it for the user instead of building it.

## Run the reporters

```sh
python3 <hworks>/scripts/retro-sessions.py --since 14d --min-sessions 5 --top 1000 > "$TASK_DIR/sessions-<date>.txt"
<hworks>/scripts/blockers.sh --since 14d > "$TASK_DIR/blockers-<date>.txt"
<hworks>/scripts/task-prune.sh > "$TASK_DIR/prune-<date>.txt"
```

`task-prune.sh` is a dry run: it lists bulk (clones, dependency installs, caches, large files) in task dirs idle for 14 days. Report its reclaimable total in the findings. Never pass `--apply`: deletion cannot be undone, so list `<hworks>/scripts/task-prune.sh --apply` for the user to run.

`retro-sessions.py` keeps only its top 15 groups per section by default, which hides most groups above the triage threshold; `--min-sessions 5 --top 1000` prints exactly the groups Triage covers. If a section prints 1000 groups, rerun with a larger `--top`. `blockers.sh` prints every class. Both take `--since YYYY-MM-DD|Nd` and `--json`, and read `adapters/local/*.env` for their sources. A missing source is reported in the output, not fatal; say in the findings file which sources were missing.

- `retro-sessions.py` prints four sections ranked by distinct sessions: command shapes, agent-written scripts (with a `where:` split of inline, scratch, and worktree), repeated helpers, and failed-then-retried calls. Each group has `sess`, `calls`, a sample, and example session paths relative to the pi sessions dir. `[exists: <name>]` means the shape names a script or skill in hworks or in `HWORKS_TOOL_DIRS`. Set `HWORKS_TOOL_DIRS` to the companion repo's tool dirs, or it will not flag tools that live there.
- `blockers.sh` prints classes as `source / kind / rule` with a count, distinct sessions, and the three latest events, then deferred decisions per repo and branch. Sources are guard blocks (`autonomy`), open questions (`open-questions`, by category), friction (`friction`, by who caught it, then category), subagent runs (`subagents`, `run-history`), and the harness audit log when configured.

## Accuracy contract

Both reporters are heuristics. A group is a lead, not a fact. Before acting on one, open two or three of its example sessions and confirm that the calls share a purpose, and what that purpose is. The same shape can cover unrelated work (a generic `import json` script group is mostly one-off parsing), and one purpose can be split across shapes. Counts are approximate: compare them to each other, not to a target. A script's location class comes from the path as written, so it can be wrong for a relative path written after a `cd`. Subagent sessions count separately, so one orchestrated program can inflate a group; check that its sessions span more than one parent session or repo.

`blockers.sh` has its own limits. Its `sess` column counts distinct session ids, or task paths when a row has no session; friction and open-questions rows have only a task path. Friction classes group by who caught it and category, not by shared cause, so one class can hold unrelated defects. Open-questions rows, and friction rows without a date, are dated by file modification time. Event detail is truncated: 200 characters stored, 90 printed. Before routing a blocker class, read the original `friction.md` and `open-questions.md` entries or status files and confirm one shared failure across independent runs.

## Triage

Triage every group in at least 5 sessions and every blocker class in at least 3; expect over a hundred groups in a 14-day window, most of them quick drops. Each lands in exactly one outcome. When a finding seems to fit two: an ignored tool (2) beats a new tool (1); a cause in a dependency (4) beats a check in this repo (3), which would only work around it; and a mistake a check can catch (3) beats a guidance edit (5).

Order verified findings by observed impact as well as distinct-session recurrence. Read the raw `cost` field of the related `friction.md` entries (review rounds, reverted commits, reruns) and cite it; do not combine unlike units into a score, and record a missing cost as unknown, not zero. A verified finding with high impact may be triaged below the frequency thresholds, with its impact evidence cited in its line.

1. Reusable tool worth building. Evidence: verified samples share one purpose; it recurs across at least 10 sessions in more than one repo or parent session; no existing tool covers it (search hworks `scripts/` and `skills/`, the companion repo, pstack, and the harness's own tools). Next step: an orchestrate unit (below).
2. Existing tool agents ignore. Evidence: a tool that covers the purpose exists (the `[exists]` flag, or one you found while checking outcome 1), and agents rebuild it by hand. Fix the routing, not the tool: the adapter (`adapters/pi.md` or the companion's), the skill's `description`, the `hughy-router` skill (`skills/hughy-router/SKILL.md`), or the prompt that told agents to do it by hand. Do not build a second tool. A tool used as intended (a gate script run on every change) is not a finding; drop it.
3. Repeated agent mistake. Evidence: the same wrong action in at least 3 sessions, such as a guard block, a malformed artifact, or a retry after the same error. Hand the class and its evidence to `/skill:correct`, which picks the enforcement level.
4. Harness or dependency defect. Evidence: the cause is in pi, pi-subagents, an MCP server, or another dependency, shown by the run's own error text or status file, and no change in this repo removes it. Search the upstream tracker and local branches for an existing issue or fix first. Draft the issue with a minimal repro in `$TASK_DIR/upstream-<slug>.md`, written from scratch with no transcript content. Filing it acts outside the machine: list it for the user. If hworks can work around it meanwhile, note the workaround as a separate finding.
5. Guidance gap. Evidence: agents made a reasonable choice the user would not want, or asked a question the guidance could have answered, in at least 3 sessions. Fix with an edit to `global/AGENTS.md` or an `agents/*.md` prompt. A guidance edit nothing enforces is the weakest fix; if the gap is a mistake a check could catch, it is outcome 3.

A finding that fits none is dropped with a one-line reason: a generic idiom with no shared purpose, a tool used as intended, a deferred decision the Autonomy rule settled correctly, or noise from a single program. Dropping is a valid outcome; forcing a weak finding into a fix costs more than missing it for one cycle.

Verified recurring harm whose cause or route is still unclear gets `investigate` instead: one discriminating question, one bounded evidence step, and the next actor. The next run resolves it into an outcome or drops it with a reason. It is not a sixth fix route, and generic idioms or single-program noise are still dropped.

After picking the outcome, add a companion Detect or Mitigate action only when the primary fix leaves a concrete gap: a way to catch the failure sooner, ideally in-session, or to make a repeat cheaper. Check what the primary route already supplies first: `/skill:correct` adds lint, CI, and test checks, and outcome 4 already allows a separate workaround finding. Route the companion as its own finding through outcomes 1-5, linked to the primary finding's id. It is never mandatory.

## Output

`$TASK_DIR/findings-<date>.md`, one line per finding:

`- [<outcome 1-5, investigate, or drop>] <id> <group or class> | <evidence: sessions, samples checked, existing tool, cost> | <next actor> | <deliverable and its completion check> | <artifact> | <state>`

The id is stable: reuse it in every run while the finding stays open, and give a companion the primary's id as its link. The next actor is an agent role, a skill such as `/skill:correct`, or "user". The artifact points at the branch, commit, `units.json` entry, or upstream draft path. The state is one of `open`, `awaiting-user`, `implemented` (landed, effect not yet seen), `effective`, or `unproven`. A drop keeps only its group and one-line reason, with no id. For `investigate`, the deliverable is the question and evidence step.

Then act on each outcome:

- Outcome 1: write the units for `../orchestrate/SKILL.md` (its Start step owns the format) in `$TASK_DIR/units.json`. A reporter or classifier unit needs the accuracy contract orchestrate describes.
- Outcomes 2 and 5: each edit is one brief for `../review-loop/SKILL.md`, or one orchestrate unit when there are several.
- Outcome 3: run `/skill:correct` with the classes.
- Outcome 4: the drafts, listed for the user.

Building runs at standard effort. Use exhaustive only for a tool whose failure is silent and costly, such as a guard, a reporter whose drop would hide a finding, or anything that deletes or rewrites. The user's questions go last in the reply, per `global/AGENTS.md`.
