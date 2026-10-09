---
name: edit-prose
description: Draft or edit prose for clarity, concision, and style per references/style-guide.md - design docs, doc review comments, issues, PR descriptions, READMEs, and draft replies. Removes AI writing tropes. Returns only the text, with no preamble or commentary. Use when asked to edit, tighten, polish, deslopify, or remove AI tropes from prose, to draft a doc section, issue, or PR description, or when invoked as a subagent to polish a draft.
---

# Prose

Draft or edit the provided text for clarity, concision, and style.

1. Read `references/style-guide.md` in this skill's directory. It applies to every text.
2. If the text is a design doc or a comment on one, also read `references/design-docs.md`. If it is an issue or a PR description, also read `references/issues-prs.md`.
3. When editing, improve form, not substance. When drafting, say only what the brief gives you.

Return only the text, with no preamble and no explanation of changes.

## When invoked as `/edit-prose`

Edit the text in `$ARGUMENTS`. If empty, ask the user for the text.

## When invoked as a subagent

The text is in the prompt. Return only the edited or drafted text.
