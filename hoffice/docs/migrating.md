# Convert an existing repository into an instance

An instance may be a repository root or a directory inside a larger git repository. Its `HOFFICE.md` marks the instance root; content and extension paths are relative to that directory. Worktrees belong to the containing repository, with instance content at the same prefix.

Use this guide for a project-memory repository that carries its own templates, scripts, skills, or system-specific instructions. Keep its content and history; let hoffice own the machinery. For a new repository, start with `templates/instance/` instead.

Paths starting with `templates/`, `scripts/`, or `docs/` below are relative to the engine checkout. Other paths are relative to the instance. Review the migration diff before committing, especially deletions, so project content is not lost with old tooling.

1. Mark the instance and replace its agent rules.

   Copy engine `templates/instance/HOFFICE.md` into the instance root and set its `name`. Replace the instance's `AGENTS.md` with engine `templates/instance/AGENTS.md`, the thin template that finds the engine and points to `docs/instance-agents.md`. Move instance-specific facts from the old instructions into its `## This instance` section; move system instructions to extensions in step 3. Keep machine-specific checkout and local-document paths in gitignored `AGENTS.local.md`.

   This makes the repository discoverable as an instance and keeps shared agent rules in the engine rather than a fork that drifts.

2. Remove the engine copies.

   Delete in-repository copies of templates, procedures, launchers (including old skills), and renderers. First check for project content or local customizations mixed into those directories: retain the content and move system-specific behavior to the extensions in step 3. Update references in current instructions to the engine's paths, not deleted local copies.

   The engine owns these files. Keeping a second copy leaves agents with competing instructions and prevents engine fixes from reaching the instance.

3. Extract every system-specific instruction.

   Follow [the extension contracts](extensions.md). Move instructions out of current agent rules, project guidance, automation recipes, and copied tooling into the instance's extension files:

   | Instruction | Instance file |
   |---|---|
   | Document host publishing, visibility, replacement, and read-back | `extensions/publisher.md` |
   | Chat, document, tracker, and code-host digest reads | `extensions/sources/<kind>.md` |
   | Tracker comparison and approved writes | `extensions/tracker.md` |
   | Extra document access values and how to read them | `extensions/access.md` |
   | Scheduled runs | `extensions/scheduler.md` |
   | Commit trailers and extra PR steps | `extensions/ship.md` |
   | Friction records, transcripts, and other retrospective evidence tooling | `extensions/evidence.md` |

   Each extension should say which tools to use, what inputs they need, and what to do when they are unavailable. Keep credentials out of these files. This preserves local capabilities without teaching the engine to assume a particular system or agent toolset.

4. Normalize current frontmatter and digest configuration.

   Compare published sources with engine `templates/published.md` and each `digests/<digest>/DIGEST.md` with `templates/digest-config.md`. Rename host-specific keys such as `<host>_slug` and `<host>_url` to `slug` and `url`, preserving their values. Keep an existing publication's slug permanent and retain its publication bookkeeping.

   Move per-system digest settings under the matching `sources[].settings`; document their meaning in `extensions/sources/<kind>.md`. Keep custom link checks under `link_patterns` as a YAML list of `kind`/`pattern` entries. Use the template's `draft_pr` and `publisher` keys where needed instead of legacy PR or publishing settings.

   The engine reads template keys, never old field names. Updating active sources and configuration is enough; history needs no rewrite.

5. File cross-project material by project.

   Dissolve any team or cross-project directory. File each document under the project it most concerns, using `projects/<name>/` and the appropriate content subdirectory. List every project in the root `README.md` table and update current navigation links to moved documents.

   A project is the unit of context loading. A second organizational hierarchy makes agents miss relevant material or load unrelated context.

6. Preserve append-only history.

   Leave sessions, decisions, and dated digests unchanged: do not normalize their frontmatter, replace old system names, or rewrite their prose. If dissolving a directory requires moving historical files, preserve their filenames and contents. Note the old repository name and layout once in the instance's `AGENTS.md`, under `## This instance`, so readers can interpret historical paths and names.

   These files record what was known at the time. They are evidence, not current configuration, and the engine does not need their old fields rewritten.

7. Validate the content and render locally.

   Set `engine` and `instance` to the absolute checkout paths, then run:

   ```bash
   "$engine/scripts/check-instance.sh" "$instance"
   ```

   Fix every finding and rerun until it passes. Then render an existing digest and a published source. Set `digest` to the directory name under `digests/` and `published_source` to the absolute path of a source under `projects/<project>/published/`:

   ```bash
   out=$(mktemp -d)
   node "$engine/scripts/render-digest.mjs" "$digest" "$out/digest.html" --instance "$instance"
   node "$engine/scripts/render-published.mjs" "$published_source" "$out/published.html"
   ```

   Inspect both HTML files for content and links. Structural checks catch layout and metadata mistakes; rendering confirms the migrated content still works with the engine. Local rendering does not authorize publishing or require an external write.

8. Cut over each machine.

   Run the engine installer with the instance checkout:

   ```bash
   "$engine/scripts/install.sh" "$instance"
   ```

   Remove retired launchers and their old configuration without removing the newly installed `hoffice-*` launchers. If the instance checkout path changed, remove its stale entry from the hoffice instance registry (`$HOFFICE_CONFIG_DIR/instances`, default `~/.config/hoffice/instances`); the installer adds the new path but does not remove the old one. Update any `HOFFICE_HOME` or `HOFFICE_DIR` overrides that still point at old paths.

   Re-point scheduled runs at the new launcher and checkout, following `extensions/scheduler.md`. Replace old launcher names, working directories, and instructions so a scheduled run cannot invoke the retired copies.

   If the checkout directory was renamed, run `git worktree repair <paths>` from the renamed main checkout, passing the current paths of its linked worktrees under `.worktrees/`. Verify `git worktree list` afterward.

   Installation records paths per machine. Retiring the old entry points and repairing worktree links prevents interactive and scheduled sessions from continuing to use the old layout.
