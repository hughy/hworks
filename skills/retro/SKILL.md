---
name: retro
description: Periodic retrospective over recent agent sessions. Runs scripts/retro-sessions.py (tooling agents keep rewriting) and scripts/blockers.sh (where runs blocked) over a window, verifies each finding in a few example sessions, and sends it to exactly one fix - a new tool built through orchestrate, a routing fix for an ignored tool, a correct pass for a repeated mistake, an upstream issue draft for a harness bug, or a guidance edit. Use for "/retro" or a request to turn recent session history into fixes; run every week or two.
---

# retro

Agents keep writing the same throwaway tools, hitting the same harness bugs, and asking the same questions. retro turns that history into fixes. Run it every week or two over the default 14-day window; a longer gap only makes the reports noisier.

It keeps no state beyond its task dir: `TASK_DIR=$(<hworks>/scripts/task-dir.sh retro)`, run from the hworks checkout. Each run writes `findings-<YYYY-MM-DD>.md` there. Read the previous one first: a finding that comes back after its fix landed means the fix did not work, and goes to a higher level (see Triage).

## Privacy

Transcripts hold private content: code, ticket text, tokens, names from every repo the agent touched. Both reporters print it (session paths, command samples, open-question text). Nothing from them goes into this repo: not in a commit, a skill, a test fixture, or a unit brief that a public branch will carry. Keep report output in `$TASK_DIR`. A fix written into hworks states the general rule, never the session it came from. A tool or rule specific to one employer goes to the private companion repo that `adapters/local/` names, when the user has one; without one, list it for the user instead of building it.

## Run the reporters

```sh
python3 <hworks>/scripts/retro-sessions.py --since 14d --min-sessions 5 --top 1000 > "$TASK_DIR/sessions-<date>.txt"
<hworks>/scripts/blockers.sh --since 14d > "$TASK_DIR/blockers-<date>.txt"
```

`retro-sessions.py` keeps only its top 15 groups per section by default, which hides most groups above the triage threshold; `--min-sessions 5 --top 1000` prints exactly the groups Triage covers. If a section prints 1000 groups, rerun with a larger `--top`. `blockers.sh` prints every class. Both take `--since YYYY-MM-DD|Nd` and `--json`, and read `adapters/local/*.env` for their sources. A missing source is reported in the output, not fatal; say in the findings file which sources were missing.

- `retro-sessions.py` prints four sections ranked by distinct sessions: command shapes, agent-written scripts (with a `where:` split of inline, scratch, and worktree), repeated helpers, and failed-then-retried calls. Each group has `sess`, `calls`, a sample, and example session paths relative to the pi sessions dir. `[exists: <name>]` means the shape names a script or skill in hworks or in `HWORKS_TOOL_DIRS`. Set `HWORKS_TOOL_DIRS` to the companion repo's tool dirs, or it will not flag tools that live there.
- `blockers.sh` prints classes as `source / kind / rule` with a count, distinct sessions, and the three latest events, then deferred decisions per repo and branch. Sources are guard blocks (`autonomy`), open questions (`open-questions`, by category), subagent runs (`subagents`, `run-history`), and the harness audit log when configured.

## Accuracy contract

Both reporters are heuristics. A group is a lead, not a fact. Before acting on one, open two or three of its example sessions and confirm that the calls share a purpose, and what that purpose is. The same shape can cover unrelated work (a generic `import json` script group is mostly one-off parsing), and one purpose can be split across shapes. Counts are approximate: compare them to each other, not to a target. A script's location class comes from the path as written, so it can be wrong for a relative path written after a `cd`. Subagent sessions count separately, so one orchestrated program can inflate a group; check that its sessions span more than one parent session or repo.

## Triage

Triage every group in at least 5 sessions and every blocker class in at least 3; expect over a hundred groups in a 14-day window, most of them quick drops. Each lands in exactly one outcome. When a finding seems to fit two: an ignored tool (2) beats a new tool (1); a cause in a dependency (4) beats a check in this repo (3), which would only work around it; and a mistake a check can catch (3) beats a guidance edit (5).

1. Reusable tool worth building. Evidence: verified samples share one purpose; it recurs across at least 10 sessions in more than one repo or parent session; no existing tool covers it (search hworks `scripts/` and `skills/`, the companion repo, pstack, and the harness's own tools). Next step: an orchestrate unit (below).
2. Existing tool agents ignore. Evidence: a tool that covers the purpose exists (the `[exists]` flag, or one you found while checking outcome 1), and agents rebuild it by hand. Fix the routing, not the tool: the adapter (`adapters/pi.md` or the companion's), the skill's `description`, the `hughy-router` skill (`skills/hughy-router/SKILL.md`), or the prompt that told agents to do it by hand. Do not build a second tool. A tool used as intended (a gate script run on every change) is not a finding; drop it.
3. Repeated agent mistake. Evidence: the same wrong action in at least 3 sessions, such as a guard block, a malformed artifact, or a retry after the same error. Hand the class and its evidence to `/skill:correct`, which picks the enforcement level.
4. Harness or dependency defect. Evidence: the cause is in pi, pi-subagents, an MCP server, or another dependency, shown by the run's own error text or status file, and no change in this repo removes it. Search the upstream tracker and local branches for an existing issue or fix first. Draft the issue with a minimal repro in `$TASK_DIR/upstream-<slug>.md`, written from scratch with no transcript content. Filing it acts outside the machine: list it for the user. If hworks can work around it meanwhile, note the workaround as a separate finding.
5. Guidance gap. Evidence: agents made a reasonable choice the user would not want, or asked a question the guidance could have answered, in at least 3 sessions. Fix with an edit to `global/AGENTS.md` or an `agents/*.md` prompt. A guidance edit nothing enforces is the weakest fix; if the gap is a mistake a check could catch, it is outcome 3.

A finding that fits none is dropped with a one-line reason: a generic idiom with no shared purpose, a tool used as intended, a deferred decision the Autonomy rule settled correctly, or noise from a single program. Dropping is a valid outcome; forcing a weak finding into a fix costs more than missing it for one cycle.

## Output

`$TASK_DIR/findings-<date>.md`, one line per finding:

`- [<outcome 1-5 or drop>] <group or class> | <evidence: sessions, samples checked, existing tool> | <next step or drop reason>`

Then act on each outcome:

- Outcome 1: write the units for `../orchestrate/SKILL.md` (its Start step owns the format) in `$TASK_DIR/units.json`. A reporter or classifier unit needs the accuracy contract orchestrate describes.
- Outcomes 2 and 5: each edit is one brief for `../review-loop/SKILL.md`, or one orchestrate unit when there are several.
- Outcome 3: run `/skill:correct` with the classes.
- Outcome 4: the drafts, listed for the user.

Building runs at standard effort. Use exhaustive only for a tool whose failure is silent and costly, such as a guard, a reporter whose drop would hide a finding, or anything that deletes or rewrites. The user's questions go last in the reply, per `global/AGENTS.md`.
