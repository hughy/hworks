# Customizing hworks

hworks is one engineer's agent layer. You can change it in two ways:

- Fork it to replace the opinions: the skills, the prose skill, and the agent prompts.
- Keep it and add an overlay repo for tool names, model rosters, and skills that are specific to one machine or employer, or that cannot be public.

Fork when you disagree with how hworks works. Use an overlay when only your environment differs. Both can apply: a fork can have overlays of its own.

Keep durable policy in shared guidance and skills, reference material in `references/`, and runtime mechanics in the existing adapters, extensions, and workflows. The [consumer notes](README.md#other-consumers) distinguish installation support from verified runtime behavior. Optional external integrations belong in overlay skills and adapters, or hoffice instance extension files when they extend project memory; they do not require a new core layer.

## How the pieces fit

```text
hworks                           skills, references, roles, adapters, model roster
  -> adapters/local/, models.d/  gitignored overlays, usually linked in from another repo
```

| Path | What it holds | When you fork |
|---|---|---|
| `global/AGENTS.md` | Global agent guidance, linked to `~/.pi/agent/AGENTS.md`, `~/.claude/CLAUDE.md`, and `~/.codex/AGENTS.md` | Replace it with your own rules; keep the Autonomy and scratch sections if you keep `autonomy.ts` and `blockers.sh` |
| `skills/edit-prose/` | A prose skill that defers to `global/AGENTS.md` | Keep, replace, or delete it |
| `references/` | Principles, the review rubric, and reference docs that agents, skills, and scripts read by path | Keep, edit, or delete them; keep `references/LICENSE` with any you keep |
| `agents/` | The `coder`, `reviewer`, `explorer`, and `synthesizer` roles for pi-subagents | Keep the roles and edit the prompts |
| `extensions/autonomy.ts` | pi guard that blocks mid-task questions and history-destroying git commands in long-running autonomous runs (orchestrate, `--unattended`, subagent children) | Keep, edit the patterns, or skip the symlink |
| `extensions/runner-exit-guard.ts` | Keeps extensions from killing a pi-subagents async runner with `process.exit()` | Keep it if your extensions force-exit headless runs; otherwise skip the symlink |
| `adapters/pi.md` | Maps hworks roles and steps to pi | Keep it unless you change harness |
| `models.conf` | Model profiles | Replace the profiles with your own |
| `scripts/` | `install.sh`, `models.sh`, `task-dir.sh`, and `blockers.sh` | Keep them. They resolve paths relative to the repo; only `global/AGENTS.md` names `~/dev/hworks`, so change that path if you clone elsewhere |
| `.claude-plugin/`, `.codex-plugin/`, `LICENSE` | Plugin manifests and license | Change the plugin name and author, and add your copyright line |

## Requirements outside the repo

- [pi](https://github.com/earendil-works/pi) with [pi-subagents](https://github.com/nicobailon/pi-subagents). The agent files and `scripts/models.sh` work only on pi. Claude Code and Codex load `skills/` only.
- The global guidance in `global/AGENTS.md`, linked into pi, Claude Code, and Codex by `scripts/install.sh`. hworks does not restate rules that live there:
  - `skills/edit-prose/references/style-guide.md` applies its "Prose" section.
  - `skills/edit-prose/references/issues-prs.md` applies its "Linear Issues" and "Commits" sections.
  - `skills/review-fanout` and the agent prompts apply its PR rules and its comment rules.
  - `extensions/autonomy.ts` and `scripts/blockers.sh` rely on its scratch rule pointing at `scripts/task-dir.sh` and on its Autonomy section.

  If you replace it, keep those sections or put the rules in the skills and remove the references; without them `edit-prose` has only the trope list and two rules of its own.

## Fork into your own layer

1. Fork the repo and clone it. Edit `global/AGENTS.md` (or replace its `~/dev/hworks` paths with your clone's), then run `scripts/install.sh`.
2. Rename the plugin. Set `name` in `.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json`, and `.codex-plugin/plugin.json`, and set `author` in both `plugin.json` files. Add your copyright line to `LICENSE`. Keep `references/LICENSE`, because the MIT license of those docs requires its notice in copies.
3. Choose the skills. Add or delete directories under `skills/`. Command skills set `disable-model-invocation: true`, so the model never sees them in its catalog. You invoke one with `/skill:<name>`, or another skill or an agent prompt reads one by path.
4. Rewrite the effort table in `skills/review-loop/SKILL.md` and the pre-push checklist in `skills/review-fanout/SKILL.md` if they do not suit you. Keep the brief format (goal, effort, verify) if it does.
5. Set your models. See [Models](#models).

## Models

Each line in `models.conf` and `models.d/*.conf` reads `<profile> <role> <model>`:

```text
mine coder       anthropic/claude-opus-5-5
mine reviewer    anthropic/claude-opus-5-5
mine explorer    anthropic/claude-haiku-4-5
mine review2     anthropic/claude-opus-5-5
mine exhaustive  -
```

- A role with a file in `agents/` is an agent role. `scripts/models.sh <profile>` writes its model to `subagents.agentOverrides.<role>.model` in pi settings. It writes to `$PI_SETTINGS` if set and to `~/.pi/agent/settings.json` otherwise, and saves a backup next to the file as `settings.json.bak-models`.
- A role named in `HWORKS_MODEL_AGENTS` is also an agent role. Use it for an agent another package ships, such as a harness's own subagent: set `HWORKS_MODEL_AGENTS=<role>[,<role>...]` in the environment or in `adapters/local/*.env` (the environment wins), and add the role's row to each profile.
- Any other role without an agent file is a slot. The review args scripts (`scripts/review-loop-args.sh`, `scripts/review-range.py`) read two slots for per-call overrides: `review2`, the second reviewer, and `exhaustive`, the `coder` model at exhaustive effort. Rename a slot in both `models.conf` and the router.
- `-` clears the override, so the role runs on the session model.
- `scripts/models.sh show` prints the active profile and flags settings that drifted from it. Run `/reload` in pi after you apply a profile.

Agent files carry no `model:` line. Keep model names in the profiles so that changing models means switching a profile, not editing prompts.

## Add or change an agent role

An agent file is markdown with frontmatter. The body is the system prompt. hworks agents use these fields, which the [pi-subagents README](https://github.com/nicobailon/pi-subagents#readme) documents in full:

| Field | hworks value | Effect |
|---|---|---|
| `tools` | No `edit` or `write` on read-only roles | `explorer`, `reviewer`, and `synthesizer` cannot change files |
| `systemPromptMode` | `replace` | The body replaces pi's base prompt instead of being appended to it |
| `inheritProjectContext`, `inheritGlobalContext` | `true` | The child loads the project's `AGENTS.md` and the global one, `~/.pi/agent/AGENTS.md` |
| `inheritSkills` | `false` | The child gets no skill catalog. pi-subagents drops hidden skills (`disable-model-invocation: true`) from a `skills:` list without a warning, and every skill an hworks agent uses is hidden, so each agent prompt names its skills by absolute path and when to read them. `scripts/test_agents.py` fails if an agent lists a hidden skill |
| `aliases` | For example, `implementer` | Other agent names resolve to the hworks role |
| `acceptanceRole` | `writer` or `read-only` | Declares whether the role writes, for pi-subagents' acceptance checks |
| `defaultContext` | `fresh` | Children start without the parent's transcript |

To add a role:

1. Create `agents/<role>.md`. `scripts/models.sh` treats every file in `agents/` as a role.
2. Add a row for the role to each profile in `models.conf`. A role missing from a profile runs on the session model.
3. Add it to the roles table in `adapters/pi.md`, and name it in the skills where it should run.

## Overlays

hworks reads two gitignored paths that an overlay fills without changing tracked files:

- `models.d/*.conf`: extra profiles in the `models.conf` format. `scripts/models.sh` reads them after `models.conf`.
- `adapters/local/*.md`: extra adapter notes. `adapters/pi.md` has every file there read after it. Where they conflict, the local file wins. `adapters/local/blockers.env`, if present, is sourced by `scripts/blockers.sh` to point it at harness-specific logs.

Keep overlay content in its own repo, so that it is versioned without becoming part of hworks:

```text
my-overlay/
  models.d/<name>.conf      profiles for your model provider
  adapters/<harness>.md     tool mappings for your harness
  skills/<skill>/SKILL.md   skills that do not belong in hworks
  global/AGENTS.md          guidance that names private systems
  hooks/                    git hooks for your hworks clone, with a private deny list
  hoffice/                  a hoffice instance for project memory (optional)
  scripts/install.sh        links the files above into place
  scripts/check.sh          the overlay's gate
```

`install.sh` links `models.d/<name>.conf` into `<hworks>/models.d/` and `adapters/<harness>.md` into `<hworks>/adapters/local/`. It also links each skill into a skills directory that your harness loads, or you add `my-overlay/skills` to `skills` in pi settings. Read the hworks path from an environment variable with a default, and refuse to overwrite a destination that is not a symlink. The overlay depends on hworks. hworks never depends on the overlay.

The other parts are for content that must stay out of public hworks:

- `global/AGENTS.md`: `install.sh` links it to `~/AGENTS.md`. pi loads that file after `~/.pi/agent/AGENTS.md` in any directory under `~`; Claude Code and Codex do not load it. Keep rules that name private systems here, not in hworks' `global/AGENTS.md`.
- `hooks/`: a deny list of private terms cannot live in hworks, because the list would leak them itself. `install.sh` links each hook into `<hworks>/.git/hooks/`, where it scans commits and pushes to hworks. Git ignores `.git/hooks/` while `core.hooksPath` is set, so leave it unset for that clone or point it at the overlay's `hooks/`.
- `hoffice/`: a directory instance whose projects, repo cards, and extension files may name private systems. Create it as `hoffice/README.md` describes under "New instance". `install.sh` registers it by running `<hworks>/hoffice/scripts/install.sh <overlay>/hoffice` when that script exists, and `scripts/check.sh` runs `<hworks>/hoffice/scripts/check-instance.sh hoffice`.

Set up a machine in this order, then start a new session:

```bash
~/dev/hworks/scripts/install.sh
~/dev/my-overlay/scripts/install.sh
~/dev/hworks/scripts/models.sh <profile>
```

`models.sh` can apply a profile from the overlay's `models.d/` only after `install.sh` has linked it. `~/dev/hworks/scripts/install.sh --check` reports drift later.

### What an adapter maps

Skills and `adapters/pi.md` name some capabilities generically, because harnesses differ. An adapter maps each one to a real tool or skill:

| Generic term | Where it appears | Map it to |
|---|---|---|
| "the closest available model", "an available model" | `adapters/pi.md` | How to list models and pick a replacement for an unavailable slot |
| "a PR-tracking tool" | `adapters/pi.md` | A tool that watches CI and review threads |
| "full review-thread bodies" | `adapters/pi.md` | A command that prints a PR's complete review-thread text, where the PR-tracking tool gives only excerpts |
| "a background-process tool" | `adapters/pi.md` | A tool that runs and watches long commands |

An adapter is a short table in the same shape as `adapters/pi.md`:

```markdown
# hworks on <harness>

| An hworks skill or adapters/pi.md says | On <harness>, use |
|---|---|
| a PR-tracking tool | `<tool>` |
```

An adapter can also override rows in `adapters/pi.md`, or add rules for its environment, such as which profile to apply.

## Check a change

After you change hworks, run `scripts/check.sh`, which runs the Python script tests, the workflow tests, and the extension tests. Then:

- Confirm that each skill's frontmatter `name` matches its directory name.
- Run `scripts/models.sh show` and confirm that each role has the model you expect.
- Run `/reload` in pi, then run `/skill:review-loop` on a small task, which spawns at least one agent.
