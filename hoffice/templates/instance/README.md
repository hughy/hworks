# Project memory

This instance holds project briefs, current state, document registries, session summaries, and decisions. Application code stays in its own repositories; code and live authoritative documents take priority over this memory.

## Quick start

1. Set `name` and the human note in `HOFFICE.md`, then initialize this directory as a git repository.
2. Find the hoffice engine through `$HOFFICE_HOME`. Run its `scripts/install.sh /absolute/path/to/this/instance` to register this instance and install launchers. If the engine was already installed, its path is also in `$HOFFICE_CONFIG_DIR/home` (default `~/.config/hoffice/home`).
3. Copy `AGENTS.local.md.example` to `AGENTS.local.md` and fill in checkout and local-document paths.
4. Follow `projects/README.md` to add a project and `repos/README.md` to register its repositories. Add the project to the table below.
5. Run `/hoffice-brief <project>` at the start of work and `/hoffice-file` at the end. Read `AGENTS.md` for read order and editing rules.

## Projects

| Project | Goal | Brief |
|---|---|---|

## Contributing

- Append dated sessions; rewrite `STATE.md` only after approval of its diff.
- Record decisions when made; supersede accepted decisions with a new file rather than rewriting them.
- Register external documents in `DOCS.md`. Link rather than mirror anything agents can fetch.
- Keep per-machine paths and private local documents out of git.
- Keep instance-specific tools in `extensions/`, not in the hoffice engine. See `extensions/README.md`.
