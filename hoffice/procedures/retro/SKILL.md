---
name: retro
description: Draft an evidence-based retrospective of how agents helped and fell short on a repository.
disable-model-invocation: true
---

# Retro

Inputs: instance root (possibly a worktree), engine root, project, repo cards, primary instance's `AGENTS.local.md` path, and scratch root. The caller owns discovery, git, and publishing. This procedure owns evidence and the draft.

Write for a team building tools for this work. Explain where agents helped, what they missed, what went wrong, who caught it, what it cost, and what would have helped. Cite every claim so readers without instance or transcript access can follow it.

## Scope

- `project`: a directory under `projects/`.
- `repos`: one or more cards in `repos/` (`org--name`). Use the named card, or all cards whose `Projects` field includes the project, confirmed with the user. Read the instance's `AGENTS.md` and supplied local instructions before collecting evidence.
- `since`: default the repo's first commit date. `until`: default today. Apply both bounds to every source; filter locally when a tool only accepts a start date.
- `slug`: default `<repo-name>-retro`. Permanent once published. A later retro of the same repo updates that document as a new version unless the user requests a separate one.
- `audience`: supplied by the user for frontmatter.

For each repo, use the last path segment of its card's `Origin`, without `.git`, as the match text. This covers the checkout, worktrees named for it, and their agent sessions. Include earlier repo names found in the card, operator messages, or git history when matching evidence through the instance's evidence extension. Use the extension's instructions to find older task records, including only those belonging to this repo. Note matches that miss or wrongly include sessions or tasks.

## 1. Collect evidence

Scratch goes in `<primary-instance>/.tmp/<YYYY-MM-DD>-retro-<slug>/`, outside the disposable worktree. Put raw output and `events.md` there, not in committed files: raw evidence can quote private transcripts. Find checkouts through the supplied `AGENTS.local.md`. Read `<instance>/extensions/evidence.md` when present for how to collect agent evidence for each repo and the bounded time window. Without it, use only git history, pull requests, and instance sessions; list agent friction and decision logs, tool-call reports, and operator transcript messages as coverage gaps. Every missing source or unavailable tool is a gap in the draft's method section, never fatal; do not substitute guessed evidence.

1. Git history from each checkout: `git log --reverse --date=short --format='%h %ad %an %s' --since=<since> --until=<until>`, plus reverts and commits with subjects starting with `fix`. These anchor the timeline and rework. Record the exact window boundaries used.
2. Pull requests via `gh`, deriving the host and `<org>/<repo>` from the card's `Origin` (handle HTTPS and SSH clone URLs). Set `GH_HOST` to that host for every command, including APIs; do not use a fixed host. List PRs with `gh pr list --repo <org/repo> --state all --search "created:>=<since> created:<=<until>" --limit 200 --json number,title,url,createdAt,mergedAt,author,headRefName`. Read each PR's review threads and reviews with `gh api repos/<org>/<repo>/pulls/<n>/comments` and `.../reviews`, and failed CI runs with `gh run list --repo <org/repo> --branch <head> --status failure`. Paginate APIs, constrain evidence to the window, and note any listing cap or inaccessible history as a coverage gap. Mark comment authors human or bot from the source.
3. Friction and decision logs, through the evidence extension when available: collect corrections, defects caught by the operator, reviewer, tests, or CI, autonomous decisions, guard blocks, and timeouts.
4. Agent tool-call reports, through the evidence extension when available: repeated command shapes and agent-written scripts show tools rebuilt by hand; failed-then-retried calls show tooling friction.
5. Operator messages from agent transcripts, through the evidence extension when available: read every matching session in the window for corrections, rejections, and repeated instructions absent from friction logs.
6. Instance evidence: the project's sessions in the window that name the repo, reading `Agent friction` first, plus decisions and repo cards. Read the engine's `templates/DOCS.md` and the instance's `extensions/access.md` if consulting registered sources; without that extension only `public`, `git`, `local`, and `mirror` apply.

## 2. Build the event list

Write one row per event in the scratch `events.md`:

`- <date> [<category>] <what happened> | <caught by> | <cost> | <what would have helped> | <source>`

- Use the engine's friction categories (`missed-defect`, `wrong-assumption`, `test-gap`, `toolchain`, `environment`, `spec-gap`, `missing-tool`, `low-value-test`) and caught-by values (`operator`, `reviewer`, `test`, `ci`, `self`). Split reviewer into `reviewer (human)` and `reviewer (agent)` only when the source supports it.
- Deduplicate events across sources. Prefer a direct PR comment URL or commit SHA over a session account.
- Cost is observed review rounds, follow-up PRs, reverted commits, or reruns. Do not estimate time. Attribute any time estimate the operator gave.
- Take `what would have helped` from operator or reviewer evidence. Prefix your own inference with `(retro)`; use `-` rather than inventing an improvement.
- Cite openable commit SHAs, PR/comment URLs, or instance session paths. Cite transcripts by date and repo, never local transcript paths, and paraphrase them.

Accuracy contract: agent evidence reports are heuristics. Before counting a tool-call group or friction/decision-log class, open two or three example sessions and confirm that calls share a purpose and belong to this repo. Drop what cannot be confirmed and say how many were dropped. Do not present raw heuristic counts as verified events.

## 3. Draft and approve

Write `projects/<project>/published/<slug>.md` from `<engine>/templates/retro.md`, filling every section from the event list. Use the shared publication fields exactly: `title`, `project`, `type`, `audience`, `authority`, `slug`, `url`, `first_published`, `last_published`, `version`, `source_state_revision`. Preserve template fields including `window` and `repos`. Set `source_state_revision` to `git -C <instance-worktree> rev-parse HEAD`; do not invent publication metadata before publishing.

- Make only evidence-backed claims. Every lesson or recommendation links to an event; each `What would have helped` item links to its rows.
- Write blamelessly about actions and systems. Name agents by role and model when recorded.
- Use severity or impact numbers only when assigned by a source. Counts are a floor of events found; say so.
- Link sources rather than copying private documents or raw transcripts into the draft.

Show the draft path and top event rows in chat. Stop until the user approves it. If they edit it, keep the event list in sync or note the hand edit. If declined, hand back the retained worktree and draft paths without publishing.

## 4. Hand back

Return the approved draft path, project, slug, event-list path, and coverage gaps. The launcher follows `<engine>/procedures/publish/SKILL.md` unless draft-only was requested; publishing still needs its own approval. When invoked directly, offer `/hoffice-publish <project> <slug>` and `/hoffice-retro` for the git workflow rather than publishing or committing here.
