---
name: handoff
description: Scope a task out of this session and write a hand-off note and a paste-ready prompt for a fresh session to own it.
disable-model-invocation: true
license: MIT (adapted from mattpocock/skills; see LICENSE)
---

# handoff

Adapted from the `handoff` skill in mattpocock/skills (commit 49dd158, MIT, see `LICENSE`). A long session, often research or planning, has scoped a task that another session should own. This skill writes the note that session starts from and the prompt that points at it. It never starts the session, pushes, or edits the target checkout.

The argument says what the next session is for. With no argument, scope the task from the recent turns and state your reading at the top of the note.

If the task needs this session's full context (a design dispute still open, a rewrite half done), keep it here, say why, and stop.

## 1. Name the target

Name the repo path and branch the next session works in, or the base it branches from. Resolve this session's `$TASK_DIR` per `global/AGENTS.md` and pick a slug for the task. Done when the target path exists and the slug is new in `$TASK_DIR`.

## 2. Gather what the next session needs

- Decisions this session settled that bear on the task, each with its evidence: `file:line`, a commit, a URL, a command and its output.
- The `open-questions.md` lines that bear on the task, states included.
- Artifacts the next session should read: paths, commits, PRs, issues, docs. Point at them; copy nothing an artifact already holds.

Check every path, test name, and line number against the target checkout (`git -C <target> ls-files`, `grep -n`). Label a fact you cannot confirm there "seen in <source>, unverified in target". Done when each fact is confirmed or labeled.

## 3. Write the note

Write `$TASK_DIR/handoff-<slug>.md`:

```markdown
# Handoff: <task>

From: <this session's $TASK_DIR>
To: <target repo path>, branch <name, or "new from <base>">

## Brief
Goal: <the outcome, and the finding or request behind it>
Effort: <quick, standard, or exhaustive>: <its phrase from hughy-router>
Verify: <the gate command, and the result that proves the goal>

## Settled
- <decision> | <evidence>

## Open
- <open-questions lines, with state>

## Out of scope
- <work the next session should not take on, and where it lives instead>

## Pointers
- <path or URL>: <what it holds>

## Skills
- `/skill:hughy-router`, plus any skill the task needs
```

Redact secrets, tokens, and personal identifiers as `<REDACTED>`. Done when every section has content or "none", every pointer resolves, and nothing secret remains.

## 4. Record and print

Append one line to `$TASK_DIR/progress.md`: `- <YYYY-MM-DD> handed off <slug> -> <note path>`. Then print the prompt for the user to paste into a new session started in the target repo:

```text
Read <absolute note path> and take over the task it describes, in <target repo path>. Start from its Brief. Treat Settled as decided unless the code contradicts it; if it does, say so before changing course.
```

**Reply:** the note path, the prompt, and anything kept in this session with the reason.
