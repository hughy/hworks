---
date: YYYY-MM-DD
project: <project directory name>
title: <one line>
agent: <agent name or role>
model: <provider/model id>
participants: []
repos:
  - name: <org/repo>
    revision: <sha at end of session, or null>
    branch: <branch or null>
prs: []
tickets: []
docs: []
tags: []
---

# <title>

Write a new dated file in `sessions/` for each session. Past sessions are append-only evidence, not current state; put later corrections in a new session.

## Goal

What the session set out to do, in one or two sentences.

## What was done

Concrete actions: files changed, commands run, PRs opened, environments touched. Link everything.

## What was learned

Facts established during the session that were not already in `STATE.md` or `notes/`. Cite the source (file and revision, doc and tab, person and channel).

## Decisions

Decisions made in this session, each with who decided and where. If a decision deserves its own record, link the file in `decisions/`.

## Open questions

Questions raised and not answered. Say who can answer each one if known.

## Agent friction

Times in this session the user corrected an agent, a reviewer, test, or CI caught a defect, or work was redone because an assumption was wrong. One line each: `- YYYY-MM-DD [<category>] <what happened> | <caught by> | <cost> | <what would have helped>`. The `procedures/retro` procedure in the engine reads these. Write "None." when there were none.

## Next actions

Only actions the user agreed to. Owner and target date if given.

## Proposed STATE.md changes

Bullet list of edits to propose. Delete this section once the diff is applied or declined.
