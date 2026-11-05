---
name: hoffice-digest
description: Summarize remote activity in a daily or weekly digest, optionally publish its running page, and open a PR for material changes. Use when the user says /hoffice-digest, "create a daily digest", "run the weekly digest", or "publish the activity digest". Runs only when the user asks to run the digest, never proactively; unattended mode requires an explicit --unattended invocation.
---

# hoffice-digest

Arguments: `<digest> [daily|weekly] [--unattended]`. Enter unattended mode only from an explicit `--unattended` invocation. Unattended runs never ask questions: stop on ambiguous discovery or git failures. Scheduling setup is in `<engine>/templates/automation.md`.

## Locate engine and instance

Engine root: `$HOFFICE_HOME`, else the single line in `${HOFFICE_CONFIG_DIR:-$HOME/.config/hoffice}/home`. If missing, stop with a setup error; never search the filesystem. Verify `<engine>/README.md` and the procedure exist.

Run `<engine>/scripts/hoffice-instances.sh` for configured instance roots. For each candidate, fetch with `git -C "$instance" fetch origin`; on failure stop. Resolve its default base with `git -C "$instance" symbolic-ref --short refs/remotes/origin/HEAD`, falling back to `origin/main`. Do not switch, pull, stash, or alter any instance checkout's own working tree.

With an explicit digest, select the instance whose default base contains `digests/<digest>/DIGEST.md` (check with `prefix=$(git -C "$instance" rev-parse --show-prefix)` then `git -C "$instance" cat-file -e "${base}:${prefix}digests/<digest>/DIGEST.md"`); no project lookup is needed. Otherwise use `<engine>/scripts/hoffice-project-for-repo.sh "$PWD"`, which returns `<instance root><TAB><project>` matches. Require one instance with `HOFFICE.md`; ask on ambiguity (unattended: stop). Never assume the engine contains project content. Read the selected instance's `AGENTS.md` and `extensions/ship.md` if present. Without ship instructions use plain commits and PRs. The target branch is the selected default base without `origin/`.

Derive `prefix=$(git -C "$instance" rev-parse --show-prefix)` for the selected instance (empty for a root instance). Git tree paths and blob URLs must include this prefix; content paths remain relative to the instance.

## Resolve digest and open refs

Take digest from arguments; otherwise find the config under `digests/*/DIGEST.md` on the default base (using `${base}:${prefix}digests/...` for tree reads) whose projects include the matched project. Require one match; ask otherwise (unattended: stop). Require that config on the default base, and take cadence from it unless passed explicitly.

From the instance checkout derive `<host>`, `<owner>`, and `<repo>` from its `origin` remote; stop if they cannot be resolved. Run `gh api --hostname <host> --paginate 'repos/<owner>/<repo>/pulls?state=open&per_page=100' --jq '.[].head.ref'` to enumerate every page of open PRs, never a fixed host or a capped `gh pr list`. Wait for successful completion before using any output: a failure on any page makes discovery incomplete and stops the run so it cannot repeat unmerged windows. Only then keep `digest/<digest>/` head branches, fetch their remote refs, and pass them as `origin/<head.ref>`. Window computation belongs to the procedure; capture run start as `period_end` before collecting sources.

## Worktree and content

Create branch `digest/<digest>/<YYYY-MM-DD>-<cadence>` and `<instance>/.worktrees/<branch>` from the default base, using `git worktree add --no-track -b`. If the branch exists locally or remotely append `-<HHMM>` once; if that collides, stop. Never reuse a previous worktree. Set `wt` to the repository worktree path and `wt_instance="$wt/${prefix%/}"`. All content reads and writes, including extensions, use `$wt_instance`; worktree operations use `$wt`.

Read `<engine>/procedures/digest/SKILL.md` with `$wt_instance` as instance root, passing digest, cadence, run start, refs, and unattended mode. The procedure owns the window, source reads, material-change test, body, link check, render, and publication. If it returns `quiet`, report the window, URL or HTML path, source counts and gaps, and stop without a commit or PR. Leave temporary output available.

## Commit and PR

Verify `git -C "$wt" status --porcelain -- . ":(top,exclude,literal)${prefix}digests/<digest>/"` is empty, checking the whole repository for out-of-scope changes. On any such change stop. Stage only `git -C "$wt_instance" add -- "digests/<digest>/"`, commit `digest: <digest> <cadence> <start date>..<end date>` with the instance's ship requirements, then push the branch. Never push a digest directly to the default branch.

Open a PR from the worktree against the default target. Use a draft PR when config `draft_pr` is true or absent; when it is false, open the PR ready for review. Its body contains only the publication URL (or unavailable), the new digest's blob URL derived from the remote, branch, and `${prefix}digests/<digest>/<name>`, window, source counts changed/unchanged/unreadable, decision/question/gap/proposal counts, and one plain sentence per active project. Note first publication when config URL was written. Do not copy digest sections or reference other PRs or issues in the body: those references create unwanted backlinks. Check for change/issue URLs, bare PR numbers, and configured identifiers and remove them. Detail stays in the committed digest.

Follow `extensions/ship.md` for post-PR steps if present; unattended runs leave review to the reviewer rather than waiting for it. Return the PR URL, digest path, publication URL or HTML path, window, and gaps. Do not delete the branch or reset any checkout.

## Failures and handoff

Any git or code-host command failure: stop, show the exact command and error, and leave the worktree with its path. Never force-push or discard work. Do not remove worktrees containing uncommitted changes or temporary renders. Return publication URL or rendered HTML path, commit or PR URL if created, and coverage gaps. Cleanup is optional, only after confirming nothing would be lost.
