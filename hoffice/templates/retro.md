---
title: "<repo> retrospective: how agents helped and where they fell short"
project: <project directory name>
type: retrospective
audience: <intended readers>
authority: informational
slug: <repo>-retro
url: null
first_published: null
last_published: null
version: 0
source_state_revision: null   # instance commit the content was drawn from
repos:
  - name: <org/repo>
    revision: <sha at the end of the window>
window: <YYYY-MM-DD> to <YYYY-MM-DD>
sources_missing: []
---

# <title>

<!--
Source of a published document, written by procedures/retro in the engine. Rules:
- Every row and claim cites a source the reader can open: commit SHA, PR or comment URL, instance session path. Transcripts are cited by date and paraphrased.
- Counts are events found, a floor, not a measurement.
- "(retro)" marks the agent's own inference; everything else was said or observed.
- No credentials, customer data, or personal data. Blameless.
-->

As of YYYY-MM-DD. One paragraph: what was built, in which repo, over what window, by whom (people and agent roles, with models where recorded), and how far it got (merged, deployed, abandoned).

## Timeline

| Date | Phase or milestone | Evidence |
|---|---|---|

## What agents did well

Practices the evidence shows working, each with a source, so the reader knows what to keep. Short.

## What went wrong

Events by category, most frequent first. One table per category, or one table sorted by category when there are few.

| Date | What happened | Caught by | Cost | Source |
|---|---|---|---|---|

## What agents missed

The subset of events agents did not catch themselves (caught by the operator, a human reviewer, a test, or CI), with what would have caught it earlier.

| What was missed | Caught by | What would have helped | Source |
|---|---|---|---|

## Where agents spent effort

Tools and commands agents rebuilt or repeated by hand across sessions, and calls that failed and were retried. Each line: what it was for, sessions and calls, whether an existing tool covers it.

## Blockers and deferred decisions

Guard blocks, timeouts, and decisions agents made without asking, grouped by class, with what settled each.

## What would have helped

Tooling, docs, checks, and brief changes, each linked to the events above. Items the operator or a reviewer named come first; `(retro)` items after.

## Method and limits

Sources read, the window, the match text used to find sessions, sources that were missing, how many heuristic groups were checked and dropped, and anything the evidence cannot show.
