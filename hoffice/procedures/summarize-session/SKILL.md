---
name: summarize-session
description: Save a session as append-only evidence and propose updates to current project state.
disable-model-invocation: true
---

# Summarize session

Inputs: instance root (possibly a worktree), engine root, resolved project, and the primary instance's `AGENTS.local.md` path. This procedure owns content; the caller owns discovery, branching, commits, and pushes. When invoked directly, hand git work to `/hoffice-file` rather than doing it here.

## Steps

1. Read the instance's `AGENTS.md` and supplied local instructions if present. Resolve the context directory as `projects/<name>`; file work spanning projects under the project it most concerns and ask if unclear. Read the instance root `README.md` (project table), then the project's `README.md`, `STATE.md`, and `DOCS.md`. Paths below are relative to the instance unless qualified with the engine root.
2. Collect facts from the conversation: goal, actions taken, files and PRs touched, commands run, facts learned, decisions, open questions, and agreed next actions. For each repo touched, capture origin, branch, and SHA (`git log -1 --format=%H`) if a checkout is available. A session records discussion, not proof that something shipped; prefer code and deployed configuration, then external documents by their registered authority, then state, notes, sessions, and digests.
3. Collect agent friction: each correction or redirection by the user, defect caught by a reviewer, test, or CI, and work redone after a wrong assumption. If `<instance>/extensions/evidence.md` exists, follow it to locate and read this session's friction notes. Without the extension or required tool, take friction only from the conversation. Do not search unrelated sessions or invent events. Use this format under `Agent friction`, or write `None.`:

   `- <YYYY-MM-DD> [<category>] <what happened> | <caught by> | <cost> | <what would have helped>`

   Categories include `missed-defect`, `wrong-assumption`, `test-gap`, `toolchain`, `environment`, `spec-gap`, `missing-tool`, and `low-value-test`. Caught by is `operator`, `reviewer`, `test`, `ci`, or `self`. Cost is observed review rounds, reverted commits, or reruns, not an estimated duration. Use `-` when no improvement was identified.
4. Collect every document URL or title mentioned, including code-host and tracker links. Compare with the project's `DOCS.md`. For each unregistered document, draft a row with `Type`, `Link`, and `Agent access` filled in, leaving `Owner` and `Authority` for the user. Chat permalinks belong in the session body or a decision's `where` field, not the document registry. Link to sources; do not mirror content unless the registry calls for it. For access values and fallbacks, read the engine's `templates/DOCS.md` and `<instance>/extensions/access.md` when present; without the extension use only `public`, `git`, `local`, and `mirror`.
5. Write a new `<context>/sessions/YYYY-MM-DD-<slug>.md` using `<engine>/templates/session.md`. Use today's date and 2-5 lowercase, hyphenated words for the slug. If that path exists, choose a distinct slug; never overwrite a prior session. Preserve the template's frontmatter field names, fill every field, and use `null` or `[]` for unknowns. Set `agent` from the running harness's agent identity, not a fixed name, and `model` from the current model ID; use `null` if unavailable. List mentioned documents in `docs:` and issues in `tickets:`.
6. Write only what happened or was said, with no invented action items, lessons, or takeaways. Cite file paths and revisions, document links and sections, or the speaker and conversation source. Use blameless language; include severity or impact numbers only if someone assigned them. For each decision made, also draft `<context>/decisions/YYYY-MM-DD-<slug>.md` from `<engine>/templates/decision.md` with `status: proposed`, and link it from the session. Supersede an earlier decision with a new linked decision, never rewrite its history.
7. Draft a coherent rewrite of `STATE.md` so it describes the present: remove obsolete claims, add supported facts, and update `Last reviewed`. Never append another version of state. Put the proposed edits in the new session's `Proposed STATE.md changes` section and show a diff in chat with the proposed `DOCS.md` rows. Stop for approval. Apply state and registry changes only after approval, then remove the proposal section from this session draft. If approval is declined, retain the proposal and report that state was not changed.
8. If a repo was substantively evaluated, offer to update its card in `repos/` and its index row in `repos/README.md`. Incidental reading does not justify a card update. Preserve the card's `Origin` and `Projects` table rows.
9. If `<instance>/extensions/tracker.md` exists, follow it for tracker offers using the `tracker` row in `DOCS.md`. Without the extension or required tool, skip and note the gap. Get explicit approval for each write (unless an unattended prompt explicitly authorizes that target):
   - For each issue in `tickets:`, offer a comment linking the session and summarizing its changes in two or three lines.
   - For each agreed next action without an issue, offer to create one in the registered container, then add its URL to `Next actions` and `tickets:`.
   - Record every completed write under `What was done`. Never change status, assignee, or priority.
10. Show `git status` for the instance worktree and hand back the new session path, approved changes, and external writes to the caller. Do not commit or push here.
