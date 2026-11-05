# External documents: <project>

Registry of documents and trackers that live outside this repo. One row per document or tracker container. The `Authority` column says which source wins for what; the `Agent access` column names how an agent can read it in this session.

Authority values: `authoritative: <what it governs>`, `informational`, `draft`, `superseded`.

Types: `PRD`, `TDD`, `design note`, `research note`, `meeting notes`, `spec`, `proto`, `runbook`, `tracker`, `repo`.

Agent access is an open list. The engine defines the system-neutral values below. Read `extensions/access.md` at the instance root, when present, for additional rows with value, system, tool, and fallback. Without it, only these values apply. Check the tools available in this session before claiming access or lack of access.

| Value | System | Typical tool | If no tool is available |
|---|---|---|---|
| `public` | Public web | Web fetch or browser | Ask for the relevant section |
| `git` | Code host or checkout | Git client, code-host tool, or file read | Ask for a checkout path |
| `local` | File on the owner's machine, resolved through `AGENTS.local.md` at the instance root | File read | Ask; do not copy it into this repo |
| `mirror` | Dated reading copy in `mirrors/` | File read | Ask for the relevant section; the live source wins |

| Doc | Type | Link | Owner | Authority | Agent access | Last checked | Notes |
|---|---|---|---|---|---|---|---|
| | | URL, with tab or section if the doc has them | person (team) | | | YYYY-MM-DD | |

Rules:

- Link, don't mirror, unless the doc is load-bearing and no tool in any session can fetch it. Mirrors go in `mirrors/<slug>.md` with `source`, `tab`, `fetched`, `fetched_by` frontmatter and are dated reading copies; the live doc wins.
- Trackers: register the container (project, team, epic, or dependency-request set), not individual issues. Issues are linked inline from sessions, decisions, and `STATE.md`. The tracker is authoritative for status, assignee, and priority; hoffice is authoritative for context and rationale. Never copy ticket status into hoffice. Tracker reads and proposed writes follow `extensions/tracker.md` at the instance root; without it, skip the tracker comparison and say so. Each write needs the user's approval.
- Never register meeting notes or chat threads as mirrors. Link the recurring notes doc once; extract decisions into `decisions/` and facts into `STATE.md`.
- `Last checked` is when someone confirmed the link resolves and the authority is still right.
