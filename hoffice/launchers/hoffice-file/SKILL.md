---
name: hoffice-file
description: Save a session and approved state changes to a hoffice instance; use --pr for review. Use when the user says /hoffice-file, "save this session", "file a session summary", or "commit the session notes". Runs only when the user asks to save and ship the session, never proactively.
---

# hoffice-file

Arguments: `[--pr]`. Discover the instance, branch in an isolated worktree, follow the engine's content procedure, then rebase and fast-forward push to the instance's default branch. The approved state diff is the review. With `--pr`, push a branch and open a draft PR instead. All content and external-write approval gates still apply.

## 1. Find the engine, instance, and project

1. Set `HOFFICE_CONFIG_DIR` to `${HOFFICE_CONFIG_DIR:-$HOME/.config/hoffice}`. Use `$HOFFICE_HOME` if set; otherwise read the single line in `$HOFFICE_CONFIG_DIR/home` as `HOFFICE_HOME`. Export both variables. If missing, empty, or not an engine containing `procedures/summarize-session/SKILL.md`, ask for the engine path. Never search the filesystem or guess an installation.
2. Run `"$HOFFICE_HOME"/scripts/hoffice-instances.sh` for validated absolute roots (from `$HOFFICE_DIR` or configured instances). On failure report stderr and ask for valid configuration; do not proceed with an unvalidated root.
3. Run `"$HOFFICE_HOME"/scripts/hoffice-project-for-repo.sh "$PWD"`. Read each line as `<instance root><TAB><project>`. Use a single match; ask the user when several instances or projects match. With no matches (exit 1, no output), including a session rooted in the instance itself, ask for the instance and project and offer to add a repo card after saving the session. Other helper errors stop discovery. Confirm the context is inside the selected instance.
4. Call the selected root `INSTANCE` and confirm `"$INSTANCE/HOFFICE.md"` exists, not a hardcoded origin. Read its `AGENTS.md` and `AGENTS.local.md` if present. Retain the local instructions path for the procedure: the file is gitignored and absent from a new worktree.

## 2. Fetch and branch in a worktree

Do not switch, pull, stash, or inspect the primary checkout's own branch or working tree. Uncommitted work there does not block this workflow. Fetch must succeed:

```bash
git -C "$INSTANCE" fetch origin --prune
base=$(git -C "$INSTANCE" symbolic-ref --short refs/remotes/origin/HEAD) || base=origin/main
default_branch=${base#origin/}
slug=<2-5 lowercase words, hyphenated>
branch="session/<project>/$(date +%F)-$slug"
prefix=$(git -C "$INSTANCE" rev-parse --show-prefix)
wt="$INSTANCE/.worktrees/$branch"
git -C "$INSTANCE" worktree add --no-track -b "$branch" "$wt" "$base"
wt_instance="$wt/${prefix%/}"
```

File work spanning projects under the project it most concerns. All content writes go to `$wt_instance`, never the primary checkout. If scratch is needed, use `"$INSTANCE"/.tmp/<date>-<slug>/` and keep it uncommitted.

## 3. Write the content

Read `"$HOFFICE_HOME"/procedures/summarize-session/SKILL.md` and follow it with `$wt_instance` as instance root, the engine root, the resolved project, and the primary instance's local instructions path. The procedure produces an append-only session, proposed state and registry changes, decisions, and approval-gated tracker offers. Show the state diff and wait; do not shortcut approval. If the user declines to save, leave the worktree and report its path.

## 4. Commit and ship

Review status and diffs from the repository worktree root `$wt` to catch changes outside the instance. Stop if any changed or staged file is outside the approved instance files. Stage explicit instance-relative file paths with `git -C "$wt_instance" add -- <files>`; never stage the whole repository. Content procedures receive `$wt_instance`, while worktree removal uses `$wt`.

Read `"$wt_instance"/extensions/ship.md` when present and follow it for commit trailers, PR body additions, and post-PR steps. Without it, use a plain commit and PR; invent no trailers or tracking steps. Review `git -C "$wt" status` and the diff, then stage only the session and approved content files. Commit with subject `session(<project>): <title>` and any extension-supplied trailers.

For the default direct-push flow, run each command only after the previous succeeds:

```bash
git -C "$wt" fetch origin
git -C "$wt" rebase "$base"
git -C "$wt" push origin "HEAD:$default_branch"
```

- On rebase conflicts, show every conflicted hunk and propose a resolution keeping both sessions' content. State stays one coherent rewrite, never two appended versions. Apply only after the user's approval, then `git -C "$wt" rebase --continue`. Never drop the other side to make it pass.
- If push is rejected because the default branch moved, fetch, rebase, and retry the fast-forward push up to three times, then stop and report. Other push failures stop immediately. Never force-push.

With `--pr`, instead push `git -C "$wt" push -u origin "$branch"`, then run `gh pr create --draft --base "$default_branch"` from inside `$wt`, targeting the instance's origin and its own forge. Derive any required host setting from that origin, never a hardcoded host or the source repo. Title: the commit subject. Body: the session's `What was done` and `Decisions`, approved state change summary (or `none`), and `DOCS.md rows added`, plus ship-extension additions. Follow the extension's post-PR step if present. Do not push to the default branch in PR mode.

## 5. Clean up and report

Only after successful shipping, remove the clean worktree with `git -C "$INSTANCE" worktree remove "$wt"`, without force. For direct push, fetch again and verify `git -C "$INSTANCE" merge-base --is-ancestor "$branch" "$base"` before deleting the integrated local branch. Retain the branch with `--pr`.

Report the commit SHA and commit URL derived from the instance's origin (or the PR URL), session path, whether state changed, and every accepted tracker write. The primary checkout was not updated; say that `git pull` brings it current when clean and on its default branch.

## Failure rules

A git or `gh` failure stops the flow except for the explicit conflict-resolution and moved-branch retry cases above. Report the exact command and error; retain the worktree and branch with their paths so nothing is lost. If cleanup fails, report what remains. Never force-push, push a non-fast-forward update to the default branch, discard uncommitted work, or use destructive reset or clean commands.
