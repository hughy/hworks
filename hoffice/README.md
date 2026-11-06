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

For an existing project-memory repository, follow [the migration guide](docs/migrating.md).

```bash
git clone https://github.com/hughy/hworks ~/dev/hworks
cp -R ~/dev/hworks/hoffice/templates/instance ~/dev/my-projects   # then git init it and fill in HOFFICE.md
~/dev/hworks/hoffice/scripts/install.sh ~/dev/my-projects
```

`install.sh` links each launcher into `~/.agents/skills/`, writes the engine path to `~/.config/hoffice/home`, and adds each instance path given to `~/.config/hoffice/instances`. Re-run it after pulling hoffice if a launcher was added.

## Local project dashboard

Render an instance's local registry as static HTML. Install the renderer dependencies once from the engine checkout:

```bash
npm ci --ignore-scripts --prefix hoffice
node hoffice/scripts/render-dashboard.mjs --instance "/path/to/project memory" "/path/to/dashboard output"
```

Run these commands from the directory containing `hoffice/`, or use the engine's absolute script path from any working directory. `--instance` must point to the directory containing `HOFFICE.md`, whether that directory is the git root or nested inside a repository. The output directory must neither contain the instance nor be inside it, including when reached through a symlink. The renderer rejects symlinks at any generated page or at the output's `projects/` or `source/` directories, or their subdirectories, before writing.

The command creates `index.html`, `projects/<project>.html`, and `source/<instance path>.html` for every Markdown file in the instance, skipping dot directories and symlinks. It overwrites those pages on later runs, leaves pages for deleted sources in place, and prints the index's `file:` URL. Open that URL in a browser. It does not edit the instance or publish anything. Links to instance Markdown open the rendered `source/` page, and each rendered page links to its raw file through an absolute `file:` URL. Other local links use `file:` URLs directly, so keep the sources available on the machine where you view the dashboard. Treat the output as private instance content.

`--variant <module.mjs>` renders the same model through a variant module that can restyle the pages or replace the index, project, and source layouts and add pages (see `scripts/lib/dashboard.mjs`). To compare several, render them all with a manifest:

```sh
node hoffice/scripts/render-prototypes.mjs --instance "/path/to/project memory" --out /tmp/prototypes --baseline /path/to/variants
```

A variants directory contributes its `*.mjs` files in name order; files starting with `_` are shared helpers, not variants. A variant's optional `meta` export gives its `id`, `title`, `approach`, `differences`, and `features`. Each variant renders into `<out>/<id>/`, and `<out>/prototypes.json` lists them for a gallery tool. Variants are per-task output and live outside the engine.

The index lists directories under `projects/`, with titles and registry fields from each project's `README.md`, open and done next-step counts and authored review dates from `STATE.md`, and links to the latest associated digests. Project pages add:

- Repository cards whose `Projects` field lists that project.
- The `Next steps` section from `STATE.md` first, with list items shown as checkboxes. GFM task items (`- [x]`) show as done; the checkboxes are read-only and change only when `STATE.md` does.
- The `Summary` and `Open questions` sections from `STATE.md`.
- `DOCS.md` rows whose `Authority` starts with `authoritative:`.
- Each associated digest's latest summary and source link.

Digest association comes from `projects[].name` in `digests/<digest>/DIGEST.md`, not the digest directory name. See [the digest config template](templates/digest-config.md). The dashboard selects the dated Markdown entry with the latest valid `period_end` in each digest directory, ignoring archive subdirectories. It skips invalid entries and configs with a diagnostic on stderr. Missing optional files and fields appear as unavailable; a review date is authored source data, not a refresh timestamp.

This phase reads local files only. Remote health, milestones, issue counts, PR counts, factory state, weekly goals, and briefings are unavailable. Links to remote sources do not mean those sources were queried.

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
