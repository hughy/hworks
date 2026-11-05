---
name: hoffice-brief
description: Brief the current project from a configured hoffice instance. Use when the user says /hoffice-brief, "brief me on this project", "where does this project stand", or "summarize the project context".
---

# hoffice-brief

Arguments: `[project]`. This launcher discovers roots and syncs the instance; the engine procedure owns the brief. Do not write content or external systems.

## 1. Find the engine and instance

1. Set `HOFFICE_CONFIG_DIR` to `${HOFFICE_CONFIG_DIR:-$HOME/.config/hoffice}`. Use `$HOFFICE_HOME` if set; otherwise read the single line in `$HOFFICE_CONFIG_DIR/home` as `HOFFICE_HOME`. Export both variables for the helpers. If missing, empty, or not an engine containing `procedures/brief/SKILL.md`, ask for the engine path; never search the filesystem or guess an installation.
2. Run `"$HOFFICE_HOME"/scripts/hoffice-instances.sh`. It returns one absolute instance root per line, honoring `$HOFFICE_DIR` or the configured instances, and validates `HOFFICE.md`. On failure report stderr and ask for valid configuration; do not proceed with an unvalidated root.
3. Run `"$HOFFICE_HOME"/scripts/hoffice-project-for-repo.sh "$PWD"`. Each result is `<instance root><TAB><project>`. With no explicit project, use the single match; ask the user to choose if there are several, or to choose an instance and project if there are none (exit 1 with no output is a normal no-match). Other errors stop discovery. If a project was named, find it as `projects/<name>` in the configured instances and ask when more than one contains it. Do not silently select the first instance or project. Accept only a context inside the chosen root.
4. Call the chosen root `INSTANCE`. Confirm `"$INSTANCE/HOFFICE.md"` exists, not a particular origin URL. Read its `AGENTS.md` and `AGENTS.local.md` if present. Keep the engine and instance roots separate.

## 2. Sync without disturbing work

Fetch `git -C "$INSTANCE" fetch origin`. Resolve the instance's default remote branch with `git -C "$INSTANCE" symbolic-ref --short refs/remotes/origin/HEAD`, falling back to `origin/main`; call it `base`, and its name without `origin/` `default_branch`.

The instance may be a subdirectory: branch, revision, and cleanliness checks apply to its entire containing repository, while content reads remain relative to `$INSTANCE`. Only when the instance checkout is clean and already on `default_branch`, run `git -C "$INSTANCE" pull --ff-only origin "$default_branch"`. Otherwise leave the checkout on its current branch and read it as-is. Do not switch branches or stash changes. A fetch or fast-forward failure is nonfatal for this read-only launcher: read local state and say it may be behind. Do not claim freshness without a successful fetch and a revision comparison.

## 3. Brief

Read `"$HOFFICE_HOME"/procedures/brief/SKILL.md` and follow it with `INSTANCE`, the resolved project, the engine root, and `"$INSTANCE/AGENTS.local.md"` when present.

At the top of its reply include one line with the instance revision read (`git -C "$INSTANCE" log -1 --format='%h %cs'`) and whether HEAD equals the fetched default branch. Report a different branch, dirty checkout, unavailable remote comparison, or failed sync. Do not update any instance file or tracker from this launcher.
