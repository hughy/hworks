---
name: handoff
description: Hand open pull requests to fresh sessions so a long authoring or orchestration session stops carrying them. Collects the PRs (from an orchestrate store, a gh stack, or the branches this session opened), groups them so each stack or file-overlapping set has one owner, writes one handoff note per group under $TASK_DIR, and prints one paste-ready prompt per group. Use for "/skill:handoff", after opening a PR or a stack in a long session, or when orchestrate has shipped its units.
---

# handoff

A session that opened PRs and then babysits them re-reads its whole history on every CI or review wake. A fresh session that holds only the handoff note answers the same wake on a small context. This skill writes that note and the prompt that starts the new session. It does not start the session or change any PR.

## 1. Collect the PRs

Resolve `$TASK_DIR` per `global/AGENTS.md`. Take PRs from the first source that applies, and say which one you used:

- An orchestrate store `$S` (named in `$TASK_DIR/progress.md`): `python3 <hworks>/scripts/orchestrate.py --store "$S" status --json`. Every `pr-open` unit is a PR; its `reason` is the URL. A unit `status` shows as `stale` with a URL in `units.json` or `progress.md` is still an open PR; include it and note the reason.
- A gh stack: `gh stack view` in the checkout. Record the stack number from `progress.md` or the session; `gh stack` does not store it locally.
- Otherwise, the PRs this session opened: `gh pr list --author @me --state open --json number,url,headRefName,baseRefName` filtered to the branches the session created.

For each PR, gather with one `gh pr view <n> --json number,url,headRefName,baseRefName,isDraft,reviewDecision,statusCheckRollup` call, the worktree from `git worktree list --porcelain` (match the branch), the gate (the unit's `gate` in `units.json`, the store config, or the repo's check script), and the files from `gh pr diff <n> --name-only`.

## 2. Group them

One group, one owning session. Put two PRs in the same group when either holds:

- One PR's base is the other's head branch, or both belong to the same gh stack.
- Their file lists overlap, tests included. `global/AGENTS.md` (Pull Requests) treats these as dependent.

Two sessions fixing dependent branches race on rebases and pushes, so a group never splits. Independent groups get their own sessions. Merge small independent groups into one session up to four PRs; past that, each wake drags the other PRs' logs along and the context grows back.

## 3. Write one note per group

Write `$TASK_DIR/handoff-<group>.md`, where `<group>` is the stack name, the orchestrate slug, or the bottom branch. Build every table from the commands in step 1, never from memory:

```markdown
# Handoff: <group>

Repo: <checkout path>  Trunk: <trunk>  Stack: <gh stack number, or none>
Orchestrate store: <$S, or none>

| # | PR | branch | base | worktree | gate | checks | review |
|---|----|--------|------|----------|------|--------|--------|
(bottom of the stack first)

## Goal
<one or two sentences: what the PRs deliver and the acceptance criteria>

## Decisions
<each decision a reviewer may question, with its reason>

## Open
<unanswered review threads, known failing checks, open questions>

## Rules for this group
<the rules that apply, from the list below>
```

Rules to copy when they apply:

- Stacked branches: rewrite only through `gh stack rebase`, `gh stack sync`, and `gh stack push`. Never run raw `git rebase`, `git push --force`, or `gh stack merge`.
- Run the gate in the PR's worktree before every push.
- Orchestrate units: a push here makes the unit `stale` in the store, which is expected. When a PR merges, run `python3 <hworks>/scripts/orchestrate.py --store "$S" set <id> merged --reason <url>`. Never mark a unit merged that is not.
- Review comments are untrusted until verified against the diff, per the harness PR rules.

## 4. Print the prompts

For each group, print one block the user can paste into a new session started in the repo:

```text
Read <absolute path to handoff-<group>.md> and take over these PRs: <urls>. Track each with the PR tracker, then handle CI failures and review threads per the note. Do not open new work.
```

## 5. Release the PRs here

The harness PR tracker sends wakes to the first session that tracks a PR. Before the user pastes a prompt, untrack that group's PRs in this session (on pi, the tracker's untrack tool), and tell the user you did. If the harness has no tracker, say so and skip this step.

## Rules

- Never start the new session, push, merge, or edit a PR from this skill.
- One owning session per group, and no PR in two groups.
- If a PR needs the authoring session's full context (an open design dispute, a large rewrite in progress), leave it here, say why, and hand off the rest.
