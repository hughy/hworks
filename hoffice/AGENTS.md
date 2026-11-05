# hoffice agent instructions

This directory is the hoffice engine. Read `README.md` for the layout and how launchers find the engine and instance, and `docs/extensions.md` before naming any external system. Instances (project content) live at a repository root or a directory inside another repo, never here.

## Rules

- hoffice is headed for public. Write nothing specific to one employer, team, project, or harness: no company or product names, internal hosts, chat channels, or tool names only one harness has. Where a step needs such a system, read the instance's extension file (`docs/extensions.md`). hoffice holds no list of the words it must not contain; a private deny list belongs in git hooks installed from outside the repo.
- `scripts/check.sh` must pass before every commit. Add a test under `tests/` (`*.test.sh` or `*.test.mjs`) for a script's behavior; `check.sh` finds it.
- Procedures (`procedures/<name>/SKILL.md`) own content and take the instance root as input. Launchers (`launchers/hoffice-<name>/SKILL.md`) own discovery and git, then follow a procedure by path. Keep each fact in one of them.
- Scripts resolve the engine root from their own location, and the instance root from an argument or `scripts/hoffice-instances.sh`. Never hardcode a local path.
- Commit through `sh -c 'git commit ...'` if your harness appends trailers to direct `git commit` calls; the commit-msg hook rejects employer names in trailers.
