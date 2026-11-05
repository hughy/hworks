---
name: hoffice-publish
description: Publish a project document and commit its verified publication record to the selected instance; use --pr for a draft PR. Use when the user says /hoffice-publish, "publish this document", "share this project document", or "update the published document". Runs only when the user asks to publish, never proactively.
---

# hoffice-publish

Arguments: `<project> <slug> [--pr]`. This launcher owns discovery and git; content belongs to the publish procedure.

## Locate engine and instance

Engine root: `$HOFFICE_HOME`, else the single line in `${HOFFICE_CONFIG_DIR:-$HOME/.config/hoffice}/home`. If missing, stop with a setup error; never search the filesystem. Verify `<engine>/README.md` and the procedure exist.

Run `<engine>/scripts/hoffice-instances.sh` for configured instance roots. An explicit project selects among them; otherwise use `<engine>/scripts/hoffice-project-for-repo.sh "$PWD"`, which returns `<instance root><TAB><project>` matches. Require one instance with `HOFFICE.md`; ask on ambiguity (unattended: stop). Never assume the engine contains project content. Read the selected instance's `AGENTS.md` and `extensions/ship.md` if present. Without ship instructions use plain commits and PRs.

Fetch `git -C "$instance" fetch origin`. On failure stop. Do not switch, pull, stash, or alter the instance checkout's own working tree. Resolve the default base with `git -C "$instance" symbolic-ref --short refs/remotes/origin/HEAD`, falling back to `origin/main`; the target branch is that ref without `origin/`.

## Prepare and publish

Resolve project from arguments or the lookup result; ask if absent or ambiguous. Resolve slug from arguments or the intended source; propose a lowercase hyphenated slug if needed and confirm. Slugs are permanent after publication. If this is a repo's implementation document, stop and direct the user to publish from that repo, registering only the result here.

Create branch `publish/<project>/<YYYY-MM-DD>-<slug>` and worktree `<instance>/.worktrees/<branch>` from the default base with `git worktree add --no-track -b`. On a name collision stop rather than reuse another run's worktree. All writes go to this worktree.

Read `<engine>/procedures/publish/SKILL.md` and follow it with the worktree as instance root. If publication is declined, fails, or lacks an extension, report the HTML/source paths and stop this launcher before commit or delivery. Preserve any draft in the worktree for the user; do not claim publication or invent bookkeeping.

## Commit and deliver

Show `git status` and verify only the intended published source and DOCS.md changed. Stage those files explicitly, then commit `publish: <project> <title> v<version>`, adding only the instance's ship requirements.

With `--pr`, push the branch and open a draft PR against the default target, using the instance remote without a hardcoded host. Include URL, audience, first publication or replacement, and change summary. Follow `extensions/ship.md` after opening it, if present.

Otherwise fetch origin, merge the updated default base into the worktree branch without rewriting commits, and push `HEAD:<default target>` only if fast-forward. On conflicts stop for the user, retaining both sides' information. On a non-fast-forward rejection, fetch and merge again up to three times, then stop. Never force-push. Report any sharing step from the publisher extension.

## Failures and handoff

Any git or code-host command failure: stop, show the exact command and error, and leave the worktree with its path. Never force-push or discard work. Do not remove worktrees containing uncommitted changes or temporary renders. Return publication URL or rendered HTML path, commit or PR URL if created, and coverage gaps. Cleanup is optional, only after confirming nothing would be lost.
