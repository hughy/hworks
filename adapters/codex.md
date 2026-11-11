# Reading an hworks skill on Codex

Resolve hworks paths from this file's checkout. In a child brief, give absolute paths to the relevant role file, references, and principles. The shared role instructions start after the frontmatter in `../agents/<role>.md`. Map paths under `~/dev/hworks` to this checkout. Skip pi tool and model settings in role files.

| Playbook says | On Codex, do |
|---|---|
| Cursor `Task`, pi `subagent`, or `poteto-agent` | Spawn a native subagent with a brief and the hworks role below. Wait for its result before using it. |
| `readonly: true` | Use a native subagent if the parent is read-only. In a writable session, launch a separate read-only Codex run as described below. |
| Cloud worker or worktree isolation | For each concurrent writer, create a separate branch worktree and give its absolute path in the brief. If the native spawn tool cannot set the working directory, launch Codex from that worktree instead. |
| Cursor model slug, `pstack-models.mdc`, or pi profile slot | Use the session's Codex model or an available Codex model override. Use low reasoning for quick, the configured default for standard, and high reasoning for exhaustive. For exhaustive, run two independent reviews and report whether they used the same model. |
| `AskQuestion` or `contact_supervisor` | Follow shared Autonomy guidance. A child reports a blocker to the parent, which owns decisions and user questions. |
| PR tracker or watcher | Use available PR tools or authenticated `gh`. Open draft PRs only when authorized. |
| Cursor or pi transcript, title, slash command, or hook | Use a Codex equivalent when available. Invoke skills by name (for example, `$hughy-router`) or read the linked skill file. |
| `/deslop`, `/no-comments`, `/unslop`, or `/technical-writing` | Apply the shared prose and comment rules. |

## Roles

- `coder`: one writer for a scoped change. Use a native worker when available.
- `reviewer`: inspect the pinned diff and return cited findings and what was checked.
- `explorer`: trace a narrow question and return cited evidence. Use a native explorer when available in a read-only session.
- `synthesizer`: combine results and surface disagreements without changing source.

Use `explorer` for `how` and `why` investigators, `synthesizer` for their final pass and the `arena` judge, and `reviewer` for `interrogate` reviewers. For `arena` candidates and `swarm` workers, choose the role by what the brief allows them to write.

Custom Codex role definitions are optional. They inherit the parent sandbox. Role instructions alone cannot make a writable session read-only.

## Interactive review

1. Before a coder starts, pin the base commit with `git merge-base <trunk> HEAD` or get the uncovered base with `scripts/review-range.py base "$TASK_DIR" <trunk> --cwd <worktree>`. Give the coder the brief and gate. Wait for the only writer to finish, then require a clean worktree and pin its resulting HEAD.
2. Run the gate from that worktree and wait for a successful exit. Quick effort ends after verification, with no review coverage recorded. For standard or exhaustive, brief each reviewer with the base SHA, head SHA, intent, and the absolute hworks reviewer prompt path. Ask for findings with file and line evidence, a verdict, and what they checked.
3. From a writable parent, put that brief in a file and launch each reviewer with `codex --ask-for-approval never exec --sandbox read-only --cd "<worktree>" - < "<brief>"`. Use a separate run for each reviewer. When the CLI default model differs from the chosen model, pass `--model <model>` to `exec`. A read-only parent can use native reviewers and collect their results at the same barrier.
4. Verify findings against the pinned diff. If a review fails or returns no evidence, repeat it. Send verified blockers to the coder for a fix, then rerun the gate and review at the new head. Before recording coverage or shipping, confirm HEAD and the clean worktree still match what reviewers saw. Record a clean review with `scripts/review-range.py record "$TASK_DIR" <trunk> <base SHA> <head SHA> codex-review --cwd <worktree>`.

Codex reference: [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) and [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode).
