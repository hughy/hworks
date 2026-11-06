# hoffice

hoffice keeps project context for coding agents: what each project is, where it stands, what was decided, and which external documents govern it. Sessions write dated summaries into a shared repository, so the next session, on any machine, starts with what the last one learned.

hoffice is the engine: templates, procedures, launchers, and scripts. Your projects live in an instance, a git repository root or a directory inside a larger git repository, marked by `HOFFICE.md`. One engine can serve several instances, for example one for work and one for personal projects. Anything specific to an employer or a toolset (a document host, a chat system, an issue tracker) is an extension the instance supplies; see [docs/extensions.md](docs/extensions.md).

## Layout

```text
procedures/<name>/SKILL.md          What a step does: brief, summarize-session, retro, publish, digest
launchers/hoffice-<name>/SKILL.md   Installed into ~/.agents/skills; find the instance, handle git, follow a procedure
templates/                          Shapes for project briefs, state docs, document registries, sessions, decisions, repo cards, retros, published docs, digests
templates/instance/                 Skeleton of a new instance
scripts/                            Launcher and procedure helpers; scripts/check-instance.sh validates an instance
docs/extensions.md                  Extension points an instance fills in
docs/instance-agents.md             Shared agent rules for instances
docs/migrating.md                   Convert an existing repository into an instance
tests/                              Run by scripts/check.sh
```

| Launcher | Procedure | When |
|---|---|---|
| `/hoffice-brief [project]` | `brief` | Start of a session: summarize where the project stands |
| `/hoffice-file [--pr]` | `summarize-session` | End of a session: file the summary, propose a `STATE.md` change, push |
| `/hoffice-retro [project] [repo]` | `retro`, then `publish` | Review how agents helped and fell short on one repo |
| `/hoffice-publish <project> <slug>` | `publish` | Share a document through the instance's publisher |
| `/hoffice-digest <digest> [daily\|weekly]` | `digest` | Summarize a period of activity from the instance's sources |

Launchers carry only what a procedure cannot know: where the engine and instance live, and git mechanics. Procedures own content and take the instance root as input.

## An instance

```text
README.md                 What the instance covers, with one row per project
HOFFICE.md                Marks the root as an instance; frontmatter `name: <instance>`
AGENTS.md                 Instructions for agents working in the instance (read order, source priority, writing rules)
AGENTS.local.md.example   Per-machine checkout and document paths; copy to AGENTS.local.md (gitignored)
projects/<name>/          One directory per project, from templates/project-*.md
repos/<org>--<name>.md    One card per git repository, from templates/repo-card.md
digests/<digest>/         Digest config (DIGEST.md) and dated digests
extensions/               The instance's extension files (docs/extensions.md)
```

Each project directory holds `README.md` (brief), `STATE.md` (what is true now, rewritten after sessions), `DOCS.md` (external document registry), `sessions/` (append-only), `decisions/`, `notes/`, `published/`, and `mirrors/`.

Everything is organized by project. Work that spans projects is filed under the project it most concerns.

## Finding the engine and the instance

- Engine root: `$HOFFICE_HOME`, else the single line in `$HOFFICE_CONFIG_DIR/home`. A launcher reads this itself, since it needs the engine to run anything else.
- Instance roots: `scripts/hoffice-instances.sh` prints one absolute path per line: `$HOFFICE_DIR` alone when set, else every non-empty line of `$HOFFICE_CONFIG_DIR/instances`. It exits non-zero with a message on stderr when no instance is configured or a root lacks `HOFFICE.md`.
- `$HOFFICE_CONFIG_DIR` defaults to `~/.config/hoffice`.

`scripts/hoffice-project-for-repo.sh [path]` matches a checkout's origin against the `Origin` field of each instance's repo cards and prints one `<instance root><TAB><project>` line per match, exiting 1 with no output when nothing matches. With several instances, the match also picks the instance.

For a directory instance, all paths in the shape above are relative to its `HOFFICE.md`, not the git toplevel.

Launchers work in a worktree of the instance's containing repository at `<instance>/.worktrees/<branch>`, branched from the instance's default branch: `git symbolic-ref --short refs/remotes/origin/HEAD`, else `origin/main`. Content lives at the same instance prefix inside that worktree; staging stays limited to instance files.

## Install

Clone the engine, create an instance (below) or [migrate an existing project-memory repository](docs/migrating.md), then register the instance:

```bash
git clone https://github.com/hughy/hworks ~/dev/hworks
~/dev/hworks/hoffice/scripts/install.sh /absolute/path/to/instance
```

`install.sh` links each launcher into `~/.agents/skills/`, writes the engine path to `~/.config/hoffice/home`, and adds each instance path given to `~/.config/hoffice/instances`. Re-run it after pulling hoffice if a launcher was added, and on each machine that uses the instance.

## New instance

Choose the form first. A repository root suits an instance of its own. A directory suits an instance that belongs with other private content, such as an hworks overlay repo (see `CUSTOMIZING.md` at the hworks root). Below, `engine` is the engine checkout, `~/dev/hworks/hoffice` by default.

1. Copy the skeleton to a path that does not exist yet, so `cp -R` copies the directory itself, dotfiles included:
   - Repository root: `cp -R "$engine/templates/instance" ~/dev/my-projects`, then `git init` it and add its remote.
   - Directory: `cp -R "$engine/templates/instance" <repo>/hoffice`. Content and extension paths are relative to that directory's `HOFFICE.md`. Launchers branch the containing repository and put worktrees at `<instance>/.worktrees/`, which the skeleton's `.gitignore` keeps untracked.
2. Set `name` and the description in `HOFFICE.md`. In `AGENTS.md`, fill `## This instance` with the repositories and hosts in scope.
3. Register it with `install.sh` as above.
4. On each machine, copy `AGENTS.local.md.example` to `AGENTS.local.md` (gitignored) and fill in checkout and local-document paths.
5. Add projects and repo cards following the instance's `projects/README.md` and `repos/README.md`, and list each project in its `README.md` table.
6. Add an extension file for each external system a procedure needs (`docs/extensions.md`). Without one, the procedure stops short: `publish` renders and stops before publishing, and `digest` lists the source as a coverage gap.
7. Run `"$engine/scripts/check-instance.sh" <instance>` and fix every finding. When the containing repository has its own check, call `check-instance.sh` from it so the instance stays valid.
8. Commit in the instance's repository.

## Local project dashboard

Render an instance as a static, split-pane workspace. Install the existing renderer dependencies once from the engine checkout:

```bash
npm ci --ignore-scripts --prefix hoffice
node hoffice/scripts/render-dashboard.mjs --instance "/path/to/project memory" "/path/to/dashboard output"
```

Run from the directory containing `hoffice/`, or use the absolute script path from any working directory. `--instance` points to the directory containing `HOFFICE.md`, whether at the git root or nested inside a repository. Output must neither contain the instance nor be inside it, including through symlinks. Before writing, the renderer rejects symlinks in generated destinations and case-insensitive page-path collisions.

Open the printed `file:` URL. The left pane lists Overview and projects ranked by how many attention reasons they have, with last activity, open steps, and a health dot (hover for reasons). A selected project's documents appear underneath in folded groups by kind, newest first. The filter searches project names and document titles.

The right pane starts with Overview: attention reasons, the next open step, and last activity. Each project view has a health strip, next steps as read-only checkboxes (completed items folded), open questions, six recent activity rows with summaries, findings and PR links, and folded STATE sections with first-sentence previews. Daily digests fold into one activity row. Properties, repositories and sources are folded below. Expand all and Collapse all affect only that project's view.

Keys: `j` / `k` move through the visible project list (including Overview); `/` focuses the filter; Escape clears it. URL hashes select views, so a view can be bookmarked. At narrow widths the panes stack. Without JavaScript, Overview still shows and each project is reachable through the sidebar’s project-page links.

The renderer writes `index.html`, `projects/<slug>.html` (the same workspace with only that project's view), and `source/<path>.html` for every regular instance Markdown file, skipping hidden directories, `node_modules`, and symlinks. Local Markdown links, heading anchors and code-span paths point to these readable pages; each source page links back to the original file. Unsafe link targets are dropped. Generated pages are overwritten on later renders; sources are never edited and nothing is published. Treat the output as private instance content.

Digest association comes from `projects[].name` in `digests/<digest>/DIGEST.md`, not the directory name. See [the digest config template](templates/digest-config.md). The latest digest age uses the latest valid `period_end`, ignoring archive subdirectories; invalid entries and configs are skipped with a diagnostic on stderr. Dated notes supply recent activity and the 12-week sparkline. STATE review dates are authored data, not refresh timestamps. Attention signals are derived from these local files only, not remote service health. Remote sources are never queried.

## Source of truth

1. Code and deployed configuration in the relevant repo.
2. External documents as registered in `DOCS.md`, per their `Authority` column.
3. `STATE.md`, then `notes/`, then `sessions/` and digests.

A session summary is evidence of what was discussed, not of what shipped.

## Working on hoffice

Run `scripts/check.sh` before every commit.

hoffice is public, so it keeps no list of private words (an employer's or a private instance's names): such a list would leak them itself. Keep yours in a private repo and point git at its hooks with `core.hooksPath`, globally or per clone; git ignores `.git/hooks/` while `core.hooksPath` is set. A clone that followed older instructions has a local `core.hooksPath hooks` that overrides yours and now points at nothing, so remove it:

```bash
git config --local --unset core.hooksPath
```
