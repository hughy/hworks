---
name: hansei
description: Periodic feedback for the operator on how they work with agents. Runs scripts/operator-signals.py over the operator's own prompts (approvals after the agent asked permission, status checks, corrections, interrupts, repeated prompts, skill use, prompt shape), verifies each finding in a few example sessions, and renders a local HTML page with candid findings and copy-paste prompts that queue each fix. Use for "/hansei" or a request for feedback on how the operator prompts, uses skills, or works with agents; run every week or two, alongside retro.
---

# hansei

Hansei is the Toyota practice of reflecting on your own shortfalls and committing to change them. `retro` looks at what agents do; hansei looks at what the operator types: where prompts cost turns, where the agent stopped to ask for a yes it did not need, where the same instruction gets retyped. The agents' transcripts supply the evidence. Run it every week or two over the default 14-day window, alongside `retro`.

It keeps no state beyond its task dir: `TASK_DIR=$(<hworks>/scripts/task-dir.sh hansei)`, run from the hworks checkout. Each run writes `findings-<YYYY-MM-DD>.json` and `hansei-<YYYY-MM-DD>.html` there. Read the previous `findings-*.json` first and fill the `previous` field: which findings went away, which came back, and whether a queued fix landed.

## Privacy

Transcripts hold private content: code, ticket text, tokens, names from every repo the agent touched. The reporter prints it, and the page quotes the operator's own prompts. Nothing from them goes into this repo: not in a commit, a skill, a test fixture, or a unit brief that a public branch will carry. Keep report output and the page in `$TASK_DIR`, and publish the page only when the operator asks. A fix written into hworks states the general rule, never the session it came from. A rule specific to one employer goes to the private companion repo that `adapters/local/` names, when the operator has one.

## Run the reporters

```sh
python3 <hworks>/scripts/operator-signals.py --since 14d > "$TASK_DIR/signals-<date>.txt"
<hworks>/scripts/blockers.sh --since 14d > "$TASK_DIR/blockers-<date>.txt"
```

`operator-signals.py` reads only sessions the operator started and strips harness injections from each message (its docstring lists the rules; `HWORKS_OPERATOR_SKIP` and `HWORKS_INJECTED_PREFIX`, set in `adapters/local/*.env`, cover harness-specific text). It prints a header with totals, then `approval`, `status-check`, `correction`, `abort`, and `repeat` groups ranked by distinct sessions, each with examples quoting the operator's message and the agent's last text before it, then `skills` and `prompt-shape`. From `blockers.sh`, read the `friction` lines whose caught-by is `operator`: they are the operator's corrections as the agents logged them. If it prints no friction lines, say so in the findings. Say in the findings which sources were missing.

## Accuracy contract

The signals are heuristics. A group is a lead, not a fact. Before stating a finding, open two or three of its example sessions and read the turns around each message. A correction can mean an unclear prompt or a bad agent turn, and the transcript often cannot tell; say which, or "unclear". A bare "yes" can answer a question the operator wanted asked. A repeat can be a deliberate template. Counts compare to each other, not to targets.

## Triage

A finding needs at least 3 sessions and an observed cost: extra turns, a correction, re-explained context, a stalled run. Each gets one owner:

- `you`: a habit or prompt change the operator makes.
- `system`: a fix in hworks. Do not act on it here; hand it to `retro` as a copy-paste prompt that names the retro outcome it likely fits (an ignored tool, a repeated mistake, a guidance gap).
- `both`: a habit change and a system fix together.

A bare approval after the agent asked permission is usually `system`: guidance should have let it proceed. When the action was irreversible (a push, a deploy, a message sent), asking was correct; drop it. Shorter prompts are not better or worse by themselves; report prompt shape only when it tracks a cost. Drop everything else with a one-line reason in `dropped`.

## Write the findings

Write each finding as upward feedback: candid, specific, quoting the operator's own words. Give one concrete better prompt or habit, and at least one copy-paste prompt that queues the fix, for example `/skill:hughy-router ...`, `/skill:retro ...`, a brief to add a line to `global/AGENTS.md`, or a reusable prompt to save as a skill. List strengths only with evidence from the same window.

## Output

1. `$TASK_DIR/findings-<date>.json` in the schema in `scripts/hansei-page.py`'s docstring, findings ordered by cost.
2. `python3 <hworks>/scripts/hansei-page.py "$TASK_DIR/findings-<date>.json" -o "$TASK_DIR/hansei-<date>.html"`
3. Open the page locally: `open` on macOS, `xdg-open` elsewhere.

The reply gives the page path and the top three findings. hansei changes no code itself; queued fixes run when the operator pastes the prompts.
