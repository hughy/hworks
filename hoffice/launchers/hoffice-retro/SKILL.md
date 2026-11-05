---
name: hoffice-retro
description: Draft and publish an agent-work retrospective in a hoffice instance; --draft skips publishing and --pr requests review. Use when the user says /hoffice-retro, "review how agents worked on this repo", or "draft an agent retrospective". Commits, pushes, and publication run only when the user asks for those actions, never proactively.
---

# hoffice-retro

Arguments: `[project] [repo] [--since YYYY-MM-DD] [--draft] [--pr]`. Discover roots, branch in an isolated instance worktree, follow `retro`, then `publish`, and rebase and fast-forward push the record to the instance's default branch. `--draft` skips publishing; `--pr` opens a draft PR instead of pushing to the default branch. All procedure approval gates still apply.

## 1. Find the engine and instance

1. Set `HOFFICE_CONFIG_DIR` to `${HOFFICE_CONFIG_DIR:-$HOME/.config/hoffice}`. Use `$HOFFICE_HOME` if set; otherwise read the single line in `$HOFFICE_CONFIG_DIR/home` as `HOFFICE_HOME`. Export both variables. If missing, empty, or not an engine containing `procedures/retro/SKILL.md`, ask for the engine path; never search the filesystem or guess an installation.
2. Run `"$HOFFICE_HOME"/scripts/hoffice-instances.sh` for validated absolute roots, honoring `$HOFFICE_DIR` or configured instances. On failure report stderr and ask for valid configuration; do not proceed with an unvalidated root.
3. Run `"$HOFFICE_HOME"/scripts/hoffice-project-for-repo.sh "$PWD"`. Each result is `<instance root><TAB><project>`. With no explicit project, use the single match; ask the user to choose when several instances or projects match. No matches (exit 1, no output) means ask for an instance and project, not guess; other errors stop discovery. If a project was named, find `projects/<name>` within configured instances and ask when more than one contains it. Confirm the project is inside the chosen root.
4. Call the chosen root `INSTANCE`. Confirm `"$INSTANCE/HOFFICE.md"` exists, not a hardcoded origin. Read its `AGENTS.md` and `AGENTS.local.md` if present; retain the latter path because it is gitignored and absent from new worktrees.

## 2. Fetch and resolve scope

Run `git -C "$INSTANCE" fetch origin --prune`; failure stops the flow. Do not switch, pull, stash, or inspect the primary checkout's own branch or working tree.

Resolve the repo from the user's named card, else match the source checkout's origin against `repos/*.md` in the instance. Ask if ambiguous. A repo without a card cannot be reviewed by this procedure; offer to add a card first. Preserve the card's `| Origin |` clone URL row and `| Projects |` project-path row. A card belonging to several projects requires the user's choice.

Read `"$HOFFICE_HOME"/procedures/retro/SKILL.md` for window, slug, and audience inputs. Confirm the permanent slug before publishing. The repo card's origin governs evidence-host access; the instance's origin governs shipping. They need not be the same host.

## 3. Branch in a worktree

```bash
base=$(git -C "$INSTANCE" symbolic-ref --short refs/remotes/origin/HEAD) || base=origin/main
default_branch=${base#origin/}
branch="retro/<project>/$(date +%F)-<slug>"
prefix=$(git -C "$INSTANCE" rev-parse --show-prefix)
wt="$INSTANCE/.worktrees/$branch"
git -C "$INSTANCE" worktree add --no-track -b "$branch" "$wt" "$base"
wt_instance="$wt/${prefix%/}"
```

All content writes go to `$wt_instance`, not the primary checkout. Evidence scratch goes in `"$INSTANCE"/.tmp/<YYYY-MM-DD>-retro-<slug>/` so it survives worktree removal. Never stage scratch or raw transcripts.

## 4. Write and publish

1. Follow `"$HOFFICE_HOME"/procedures/retro/SKILL.md` with `$wt_instance` as instance root, the engine root, resolved inputs, the primary instance's local instructions path, and the scratch path. The procedure reads the instance's evidence extension; missing evidence sources are method gaps, not fatal errors. Stop at draft approval until the user approves.
2. Unless `--draft`, read `"$HOFFICE_HOME"/procedures/publish/SKILL.md` and follow it for the same worktree, project, and slug. It owns scanning, rendering, publication approval, metadata, and the registry row. Do not bypass its approval or guess a publisher. If no publisher is configured, retain the rendered local artifact, report that publication stopped, and ask whether to ship the record as an unpublished draft. Do not claim it was published.

If the user declines the draft or publication prompt, stop, leave the worktree, and report its path. `--draft` is the explicit route for shipping without publishing.

## 5. Commit and ship

Review status and diffs from the repository worktree root `$wt` to catch changes outside the instance. Stop if any changed or staged file is outside the approved instance files. Stage explicit instance-relative file paths with `git -C "$wt_instance" add -- <files>`; never stage the whole repository. Content procedures receive `$wt_instance`, while worktree removal uses `$wt`.

Read `"$wt_instance"/extensions/ship.md` when present for commit trailers, extra PR body lines, and post-PR tracking. Without it, use a plain commit and PR with no invented trailers or tracking steps. Review the worktree status and diff, stage only the approved source, metadata, and registry changes, and commit with subject `retro(<project>): <title> v<version>` using the recorded version. For `--draft` or an approved unpublished record, use `retro(<project>): draft <title>` instead; do not invent a published version.

For direct push, run each command only after the previous succeeds:

```bash
git -C "$wt" fetch origin
git -C "$wt" rebase "$base"
git -C "$wt" push origin "HEAD:$default_branch"
```

- On rebase conflicts, show every conflicted hunk, propose a resolution preserving both sides, and wait for approval before applying it and running `git -C "$wt" rebase --continue`. Keep state a coherent rewrite and registry rows from both sessions. Never drop the other side to pass the rebase.
- If push is rejected because the default branch moved, fetch, rebase, and retry the fast-forward push up to three times; then stop and report. Other push failures stop immediately. Never force-push.

With `--pr`, instead run `git -C "$wt" push -u origin "$branch"`, then `gh pr create --draft --base "$default_branch"` from inside `$wt`, targeting the instance's origin on its own forge. Derive any required host setting from that origin, with no fixed host or carryover from evidence commands. Title: the commit subject. Body: published URL (or `draft, not published`), repo and window, missing evidence sources, and ship-extension additions. Follow its post-PR step when present. Do not push to the default branch in PR mode.

## 6. Clean up and report

Only after successful shipping, remove the clean worktree with `git -C "$INSTANCE" worktree remove "$wt"`, without force. For direct push, fetch again and verify `git -C "$INSTANCE" merge-base --is-ancestor "$branch" "$base"` before deleting the integrated local branch. Retain the branch with `--pr`.

Report the published URL and any sharing restrictions returned by the publisher (or `not published`), commit SHA and URL derived from the instance's origin (or PR URL), source path, scratch path, and missing evidence sources. The primary checkout was not updated; say that `git pull` brings it current when clean and on its default branch.

## Failure rules

A git or `gh` failure stops the flow except for the explicit conflict-resolution and moved-branch retry cases above. Report the exact command and error, leave the worktree and branch in place, and give their paths. If cleanup fails, report what remains. A publication followed by a git failure may already be live: report its URL and retain the local metadata, never republish blindly. Never force-push, push a non-fast-forward update to the default branch, discard uncommitted work, or use destructive reset or clean commands.
