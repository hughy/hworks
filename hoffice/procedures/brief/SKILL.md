---
name: brief
description: Read one project's shared context and return a short, sourced status.
disable-model-invocation: true
---

# Brief

Inputs: instance root, project (`projects/<name>`), engine root, and the primary instance's `AGENTS.local.md` path when reading a worktree. The launcher owns discovery and git; this procedure is read-only.

## Steps

1. Read the instance's `AGENTS.md` and the supplied local instructions if present. Resolve the project within the instance; ask if ambiguous. Below, `<context>` means `projects/<name>`.
2. Read in one batch: the instance root `README.md` (project table), `<context>/README.md`, `<context>/STATE.md`, `<context>/DOCS.md`, the three newest files in `<context>/sessions/` (ignore `README.md`), and every card in `repos/` listed by the context README. Inspect `digests/*/DIGEST.md` for coverage of this project and read the newest dated digest among the covering directories, if any. All these paths are relative to the instance.
3. If `AGENTS.local.md` lists a checkout for a repo in scope, run `git -C <path> log -1 --format='%H %cs'` and `git -C <path> branch --show-current`. Compare the SHA with the repo card's `Revision`. Report drift; do not evaluate the repo unless asked.
4. For `DOCS.md` access, use the engine's `templates/DOCS.md` values (`public`, `git`, `local`, `mirror`) and read `<instance>/extensions/access.md` if present for extra values and fallbacks. If `<instance>/extensions/tracker.md` exists and `DOCS.md` has a `tracker` row, follow the extension to read in-progress, in-review, and recently completed (last 14 days) items in that container. Compare with `STATE.md`: flag next steps already done and active items absent from state. Do not write. If the extension, row, or required tool is missing, skip the comparison and say why; never guess a system.
5. Reply in this order, under 35 lines, including the launcher's revision line:
   - One paragraph: what the project is and its status, citing `STATE.md`'s `Last reviewed` date.
   - Open questions from `STATE.md`.
   - Next steps from `STATE.md`, with live tracker status when available.
   - What the last sessions did, one line per session, newest first. Add one line from the newest covering digest's project subsection, its date, and its published URL when recorded in the digest or its `DIGEST.md`. If no published link is recorded, cite the digest path.
   - Drift: repo card revision versus local checkout, state versus tracker, and relevant `Known gaps`. Include skipped checks.
6. Do not update any file. If `STATE.md` looks stale, say so and offer `/hoffice-file` or an evaluation.
