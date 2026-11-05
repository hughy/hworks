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
