# Instance agent instructions

This repository is shared project memory, not application code. Code and deployed configuration win when they disagree with this repository; propose the corresponding context update.

## Repository role

- `projects/<name>/` is the unit of work and context loading. File work spanning projects under the project it most concerns. `repos/<org>--<name>.md` describes a git repository, which may serve several projects.
- Repo cards are pointers, not checkouts. Per-machine paths belong in gitignored `AGENTS.local.md`, never in committed files.
- Find the hoffice engine through `$HOFFICE_HOME`, else the single line in `$HOFFICE_CONFIG_DIR/home` (`HOFFICE_CONFIG_DIR` defaults to `~/.config/hoffice`). Paths below starting with `templates/`, `procedures/`, `scripts/`, or `docs/` are relative to that engine. Other paths are relative to this instance.

## Read order on start

1. Read instance `README.md` and its project table.
2. Read the scoped project's `README.md`, `STATE.md`, then `DOCS.md` to learn which external documents govern it and how to fetch them.
3. Read the three newest project `sessions/` files and the newest digest whose `DIGEST.md` covers the project, if any. Read older history only when needed.
4. Read `repos/<org>--<name>.md` for every repository you will read or discuss.
5. Read `AGENTS.local.md`, if present, for checkout and local-document paths.

If the project is unclear, match the checkout's origin with the engine's `scripts/hoffice-project-for-repo.sh`. If that does not resolve it, ask which project before loading project context.

## Source priority

1. Code and deployed configuration at the relevant branch or revision.
2. Live external documents registered in `DOCS.md`, at the linked section or tab, according to their `Authority` column. A draft does not prove something shipped.
3. `STATE.md`.
4. `notes/`.
5. `sessions/` and digests: evidence of discussion or activity, not of current behavior.

Report missing context rather than guessing. A live document wins over a dated reading copy.

## External documents

- Each project's `DOCS.md` registers external documents. Column meanings and the engine's `Agent access` values (`public`, `git`, `local`, `mirror`) are in engine `templates/DOCS.md`. Read `extensions/access.md`, if present, for additional values and tools.
- Respect each document's `Authority` scope. Superseded documents are history, not guidance.
- `Agent access` identifies a way to read, not a permission grant. Check the available tools before declaring a document unreadable. Read the live document if reachable; otherwise use a dated mirror or ask for the relevant section. Never infer unread content.
- Mirror only load-bearing documents that no session's tooling can fetch, in `projects/<name>/mirrors/<slug>.md`, with `source`, `tab`, `fetched`, and `fetched_by` frontmatter. Report disagreement with the live document.
- Resolve `local` documents through `AGENTS.local.md` and read them in place. Never copy them here or publish them.
- Link meeting notes and discussion threads; do not mirror them. Record a thread's decision in `decisions/` with the permalink in `where`.
- During session summarization, propose a `DOCS.md` row for each newly mentioned document URL. The user supplies its authority.

## Trackers

- Read `extensions/tracker.md` before tracker work. Without it, skip the comparison and report the gap; never guess a system.
- Register tracker containers as `tracker` rows in `DOCS.md` and link them from the project README. Link individual issues inline from sessions, decisions, and next steps.
- The tracker owns status, assignee, priority, and backlog. This instance owns context, rationale, and decisions. Do not mirror ticket status here.
- Report drift between the tracker and `STATE.md` and propose which side to fix. Read through the extension's tools; each write requires the user's explicit approval. Record completed writes in the session summary.

## Writing rules

### Session summaries

- Use engine `templates/session.md`, keeping every frontmatter field (`null` or `[]` when unknown), including the agent and model attribution.
- Write one file per session at `projects/<name>/sessions/YYYY-MM-DD-<slug>.md`. File sessions spanning projects under the project they most concern.
- Record the goal, work, learning, decisions, open questions, and agreed next actions. Do not invent action items or lessons.
- Link PRs, commits, issues, and documents by URL; cite repo revisions by SHA.
- Sessions are append-only. Correct only broken links or factual errors in past sessions, and note the correction at the bottom.

### STATE.md

- Rewrite, never append. Describe the present architecture, deployment status, open questions, next steps, and `Last reviewed` date.
- After the session summary, show the proposed `STATE.md` diff and wait for approval before applying it.
- Remove obsolete claims. Move resolved questions into a decision or session rather than a resolved list.

### Decisions, repo cards, and notes

- Use engine `templates/decision.md` in `projects/<name>/decisions/YYYY-MM-DD-<slug>.md`. File decisions spanning projects under the project they most concern.
- Decision status is `proposed`, `accepted`, or `superseded`. Supersede an accepted decision with a new file and links both ways; never rewrite it. Record who decided and where.
- Change a repo card's `Last evaluated` and `Revision` only after an actual evaluation, not incidental reading.
- Edit notes in place; date substantive changes at the top.

### Style

- Write blameless accounts of actions and systems, not judgments of people.
- Do not invent severity levels, impact metrics, or targets. Attribute estimates and label them as estimates.
- Prefer dated facts and source links. Link to detail rather than copying it.

## Workspace model and finding repositories

- Read other checkouts by path; do not create, edit, or delete files outside this instance during an instance session. For code changes, continue in a session rooted in the relevant repository.
- Locate checkouts by origin URL, not directory name. Check `AGENTS.local.md`, then ask. Do not clone from an instance session.
- Use `.tmp/YYYY-MM-DD-<slug>/` for instance scratch (gitignored); use a temporary directory for disposable command-internal files.
- Isolate branch work in `.worktrees/<branch>`. Launchers branch from the instance's default branch (`git symbolic-ref --short refs/remotes/origin/HEAD`, else `origin/main`).
- Never discard uncommitted work, force-push, or run destructive git operations in this instance or a checkout being read.
- Add a repo card when a repository becomes recurring context.

## Procedures and launchers

Procedures live in the engine and take this instance root as input. Launchers installed by engine `scripts/install.sh` find the engine and instance and own git; procedures own content.

| Launcher | Engine procedure | Use |
|---|---|---|
| `/hoffice-brief [project]` | `procedures/brief/SKILL.md` | Load project context and summarize current state |
| `/hoffice-file [--pr]` | `procedures/summarize-session/SKILL.md` | Summarize this session and propose a state diff |
| `/hoffice-retro [project] [repo]` | `procedures/retro/SKILL.md`, then `procedures/publish/SKILL.md` | Review agent work on one repo and publish the result |
| `/hoffice-publish <project> <slug>` | `procedures/publish/SKILL.md` | Publish or replace a document |
| `/hoffice-digest <digest> [daily\|weekly]` | `procedures/digest/SKILL.md` | Summarize activity for a configured period |

Read engine `docs/extensions.md` for extension contracts. `extensions/sources/<kind>.md` supplies digest sources; missing sources become coverage gaps. `extensions/evidence.md` supplies friction and transcript evidence for retros and session summaries; without it, report those sources as coverage gaps. `extensions/scheduler.md` supplies scheduling; without it, run by hand. `extensions/ship.md` supplies extra commit and PR steps; without it, use plain commits and PRs. Unattended digests never edit `STATE.md` and open draft PRs for review.

## Publishing

- Read `extensions/publisher.md` before publishing. Without it, render HTML, report the path, and stop before external writes.
- Choose the source by subject: documentation of one repo's implemented behavior belongs in that repo's `docs/`; this instance only registers its published URL. Cross-system design, status, decisions, and narratives belong in `projects/<name>/published/` for the project they most concern.
- Never publish `STATE.md`, sessions, or local documents directly. Draft with engine `templates/published.md` and set `source_state_revision`. Status reports are dated snapshots, not live views.
- Keep `slug` permanent. Before replacing a version, show what changed and get approval. Follow the publisher extension's initial visibility rules; sharing remains the user's step.
- Scan for credentials, personal or customer data, and hostnames inappropriate for the audience. Stop on a hit.
- Register each published document in `DOCS.md` using the publisher extension's `Agent access` value.
- External writes require approval for each write, unless an unattended run's prompt explicitly authorizes the target.
