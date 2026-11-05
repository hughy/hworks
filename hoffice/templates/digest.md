---
date: YYYY-MM-DD
digest: <directory under digests/>
projects: [<project names covered>]
cadence: <daily | weekly>
period_start: <ISO 8601 with offset; inclusive>
period_end: <ISO 8601 with offset; exclusive. The next run starts here>
agent: <agent name>
model: <provider/model id>
run: <unattended | interactive>
baseline: false            # true only for a project's first digest
url: null            # the running published page this digest was published to, or null if publish failed
sources:
  # One entry per source checked, including ones with no change, so the next run and reviewers can
  # see coverage. `marker` is what the next run compares against.
  - kind: <configured source kind>   # chat | documents | tracker | code-host
    ref: <source identifier or URL>
    marker: <extension-defined marker, or null>
    status: <changed | unchanged | unreadable>
prs: []
tickets: []
docs: []
tags: [digest]
---

# <Cadence> digest: <digest title>, <period_start date> to <period_end date>

<!--
Every PR, commit, tracker issue, chat channel or message, and document is a Markdown link.
<engine>/scripts/render-digest.mjs --check fails on unlinked artifacts in every section above Coverage gaps.
Sections from Background through Open questions appear in the running published page.
Inside a section, use one `### <project label>` subsection per project from DIGEST.md that has items,
in DIGEST.md order. Put items spanning projects under the project they most concern. Omit empty subsections;
write "None." when a whole section is empty.
-->

## Current status

One `### <project label>` subsection for every project, even when nothing changed. Three to eight bullets each on where the project stands as of period_end: work in flight (tracker issues in progress or review, open PRs), what is blocked, and the next milestone. Built from remote sources; `STATE.md` on the instance default branch is background only. The published page shows this section from the newest digest only.

## Background

Baseline digest only; delete otherwise. One short paragraph per project on what it is, from its README and `STATE.md`, with links to its PRD and tracker, and one sentence on how the projects relate.

## Summary

Three to six sentences across all projects on what changed in the period. Facts only, each traceable to an item below. No subsections.

## Decisions and commitments

Decisions or commitments stated in the period, with who stated them and the permalink or doc link, under project subsections. These are candidates for `decisions/`; this file does not make them accepted.

## Discussion

Under project subsections, grouped by topic, not by channel. Each item: one or two sentences of paraphrase, the date, and a chat permalink. No long verbatim quotes.

## Documents

Documents created or edited in the period, under project subsections. Name, link with tab, what changed in a sentence, and the source of that claim (revision, version, or comment). Include unregistered documents linked from chat or tracker in the period, marked `(linked, not registered)`.

## Code

Merged PRs and notable default-branch commits, under project subsections, per repo, with links and SHAs.

## Tracker activity

Tracker events in the period (created, completed, commented), under project subsections, dated and linked. Events, not current status.

## Open questions

Questions raised in the period that were not answered, under project subsections, with who asked and where.

## Coverage gaps

Sources that could not be read, and why (no tool, auth failure, timeout, not a channel member).

## Proposed STATE.md changes

One `### projects/<name>/STATE.md` subsection per project with edits a reviewer might apply. The automation never edits `STATE.md`.

## Proposed DOCS.md rows

Documents seen in the period that are not registered, under `### projects/<name>/DOCS.md`, with `Type`, `Link`, `Agent access` filled in and `Owner` and `Authority` left blank.
