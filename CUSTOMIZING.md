# Customizing hworks

hworks is one engineer's layer over pstack. You can change it in two ways:

- Fork it to replace the opinions: the router, the allowlist, the prose skill, and the agent prompts.
- Keep it and add an overlay repo for tool names, model rosters, and skills that are specific to one machine or employer, or that cannot be public.

Fork when you disagree with how hworks works. Use an overlay when only your environment differs. Both can apply: a fork can have overlays of its own.

## How the pieces fit

```text
cursor/plugins/pstack            upstream, written for Cursor
  -> hughy/pstack, upstream      byte-exact copy
  -> hughy/pstack, main          upstream plus install fixes (see pstack/MIRROR.md)
  -> hworks/pstack/              git subtree of the mirror's main; never edited here
  -> hworks                      router, allowlist, roles, adapter, model roster
  -> adapters/local/, models.d/  gitignored overlays, usually linked in from another repo
```

| Path | What it holds | When you fork |
|---|---|---|
| `global/AGENTS.md` | Global agent guidance, linked to `~/.pi/agent/AGENTS.md`, `~/.claude/CLAUDE.md`, and `~/.codex/AGENTS.md` | Replace it with your own rules; keep the Autonomy and scratch sections if you keep `autonomy.ts` and `blockers.sh` |
| `skills/hughy-router/` | The router: routes, effort levels, and the deltas that override pstack playbooks | Rename it and rewrite the routes and deltas to match how you work |
| `skills/edit-prose/` | A prose skill that defers to `global/AGENTS.md` | Keep, replace, or delete it |
| `skills/<name>` symlinks | The allowlist of pstack skills that load | Choose your own with `scripts/skill.sh` |
| `DIVERGENCE.md` | Why each pstack skill is not linked | Rewrite the reasons to match your choices |
| `agents/` | The `coder`, `reviewer`, `explorer`, and `synthesizer` roles for pi-subagents | Keep the roles and edit the prompts |
| `extensions/autonomy.ts` | pi guard that blocks mid-task questions and history-destroying git commands | Keep, edit the patterns, or skip the symlink |
| `extensions/runner-exit-guard.ts` | Keeps extensions from killing a pi-subagents async runner with `process.exit()` | Keep it if your extensions force-exit headless runs; otherwise skip the symlink |
| `adapters/pi.md` | Maps Cursor terms in pstack to pi | Keep it unless you change harness |
| `models.conf` | Model profiles | Replace the profiles with your own |
| `scripts/` | `install.sh`, `skill.sh`, `models.sh`, `task-dir.sh`, and `blockers.sh` | Keep them. They resolve paths relative to the repo; only `global/AGENTS.md` names `~/dev/hworks`, so change that path if you clone elsewhere |
| `.claude-plugin/`, `.codex-plugin/`, `LICENSE` | Plugin manifests and license | Change the plugin name and author, and add your copyright line |
| `pstack/` | The mirror subtree | Do not edit it (see [Resync pstack](#resync-pstack)) |

## Requirements outside the repo

- [pi](https://github.com/earendil-works/pi) with [pi-subagents](https://github.com/nicobailon/pi-subagents). The agent files and `scripts/models.sh` work only on pi. Claude Code and Codex load `skills/` only.
- The global guidance in `global/AGENTS.md`, linked into pi, Claude Code, and Codex by `scripts/install.sh`. hworks does not restate rules that live there:
  - `skills/edit-prose/references/style-guide.md` applies its "Prose" section.
  - `skills/edit-prose/references/issues-prs.md` applies its "Linear Issues" and "Commits" sections.
  - The router applies its PR rules and its comment rules.
  - The router, `extensions/autonomy.ts`, and `scripts/blockers.sh` rely on its scratch rule pointing at `scripts/task-dir.sh` and on its Autonomy section.

  If you replace it, keep those sections or put the rules in the skills and remove the references; without them `edit-prose` has only the trope list and two rules of its own.

## Fork into your own layer

1. Fork the repo and clone it. Edit `global/AGENTS.md` (or replace its `~/dev/hworks` paths with your clone's), then run `scripts/install.sh`.
2. Rename the router. Rename `skills/hughy-router/` and change the `name:` in its frontmatter to match the new directory name. Then run `git grep -n hughy-router -- ':!pstack'` and update each hit. The hits are in `README.md`, `CUSTOMIZING.md`, `DIVERGENCE.md`, `adapters/pi.md`, `agents/coder.md`, `models.conf`, and `scripts/models.sh`. Start a task with `/skill:<new-name> <task>`.
3. Rename the plugin. Set `name` in `.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json`, and `.codex-plugin/plugin.json`, and set `author` in both `plugin.json` files. Add your copyright line to `LICENSE`. Keep `pstack/LICENSE`, because pstack's MIT license requires its notice in copies.
4. Choose the allowlist. `scripts/skill.sh list` shows which pstack skills are linked. `scripts/skill.sh enable <name>` links a skill and deletes its `DIVERGENCE.md` row. `scripts/skill.sh disable <name> "<reason>"` unlinks a skill and adds a row with the reason and the current mirror commit. pstack skills set `disable-model-invocation: true`, so the model never sees them in its catalog. You invoke one with `/skill:<name>`, or the router or an agent prompt reads one by path.
5. Rewrite the router. Its effort table, routes, and deltas are opinions. Keep the brief format (goal, effort, verify) if it suits you. Playbooks under `pstack/skills/poteto-mode/playbooks/` need no enabling, because the router reads them by path.
6. Set your models. See [Models](#models).
7. Point resyncs at the mirror you follow. See [Resync pstack](#resync-pstack).

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
- Any other role without an agent file is a slot. The router reads two slots for per-call overrides: `review2`, the second reviewer, and `exhaustive`, the `coder` model at exhaustive effort. Rename a slot in both `models.conf` and the router.
- `-` clears the override, so the role runs on the session model.
- `scripts/models.sh show` prints the active profile and flags settings that drifted from it. Run `/reload` in pi after you apply a profile.

Agent files carry no `model:` line. Keep model names in the profiles so that changing models means switching a profile, not editing prompts.

## Add or change an agent role

An agent file is markdown with frontmatter. The body is the system prompt. hworks agents use these fields, which the [pi-subagents README](https://github.com/nicobailon/pi-subagents#readme) documents in full:

| Field | hworks value | Effect |
|---|---|---|
| `tools` | No `edit` or `write` on read-only roles | `adapters/pi.md` maps pstack's `readonly: true` to those roles |
| `systemPromptMode` | `replace` | The body replaces pi's base prompt instead of being appended to it |
| `inheritProjectContext`, `inheritGlobalContext` | `true` | The child loads the project's `AGENTS.md` and the global one, `~/.pi/agent/AGENTS.md` |
| `inheritSkills` | `false` | The child gets no skill catalog. pi-subagents drops hidden skills (`disable-model-invocation: true`) from a `skills:` list without a warning, and every skill an hworks agent uses is hidden, so each agent prompt names its skills by absolute path and when to read them. `scripts/test_agents.py` fails if an agent lists a hidden skill |
| `aliases` | For example, `poteto-agent` | pstack's agent names resolve to the hworks role |
| `acceptanceRole` | `writer` or `read-only` | Declares whether the role writes, for pi-subagents' acceptance checks |
| `defaultContext` | `fresh` | Children start without the parent's transcript |

To add a role:

1. Create `agents/<role>.md`. `scripts/models.sh` treats every file in `agents/` as a role.
2. Add a row for the role to each profile in `models.conf`. A role missing from a profile runs on the session model.
3. Map pstack roles to it in the tables in `adapters/pi.md`, and name it in the router where it should run.

## Overlays

hworks reads two gitignored paths that an overlay fills without changing tracked files:

- `models.d/*.conf`: extra profiles in the `models.conf` format. `scripts/models.sh` reads them after `models.conf`.
- `adapters/local/*.md`: extra adapter notes. The router reads every file there after `adapters/pi.md`. Where they conflict, the local file wins. `adapters/local/blockers.env`, if present, is sourced by `scripts/blockers.sh` to point it at harness-specific logs.

Keep overlay content in its own repo, so that it is versioned without becoming part of hworks:

```text
my-overlay/
  models.d/<name>.conf      profiles for your model provider
  adapters/<harness>.md     tool mappings for your harness
  skills/<skill>/SKILL.md   skills that do not belong in hworks
  scripts/install.sh        links the files above into place
```

`install.sh` links `models.d/<name>.conf` into `<hworks>/models.d/` and `adapters/<harness>.md` into `<hworks>/adapters/local/`. It also links each skill into a skills directory that your harness loads, or you add `my-overlay/skills` to `skills` in pi settings. Read the hworks path from an environment variable with a default, and refuse to overwrite a destination that is not a symlink. The overlay depends on hworks. hworks never depends on the overlay.

### What an adapter maps

The router names some capabilities generically, because harnesses differ. An adapter maps each one to a real tool or skill:

| Generic term | Where it appears | Map it to |
|---|---|---|
| "the closest available model", "an available model" | `adapters/pi.md`, the effort section of the router | How to list models and pick a replacement for an unavailable slot |
| "a PR-tracking tool" | `adapters/pi.md`, the router's PR delta | A tool that watches CI and review threads |
| "full review-thread bodies" | `adapters/pi.md`, the router's Ship route | A command that prints a PR's complete review-thread text, where the PR-tracking tool gives only excerpts |
| "a background-process tool" | `adapters/pi.md` | A tool that runs and watches long commands |
| "an issue-planning skill" | The router's Long run route and deltas | A skill that drafts issues for a multi-PR program |
| "a multi-agent coordinator" | The router's Long run route | A coordinator with per-area threads and shared memory, if your harness has one |

An adapter is a short table in the same shape as `adapters/pi.md`:

```markdown
# <router> on <harness>

| The router or adapters/pi.md says | On <harness>, use |
|---|---|
| a PR-tracking tool | `<tool>` |
| an issue-planning skill | `<skill>` |
```

An adapter can also override rows in `adapters/pi.md`, or add rules for its environment, such as which profile to apply.

## Resync pstack

`pstack/` is a squashed git subtree of the mirror's `main` branch:

```bash
git subtree pull --squash --prefix pstack https://github.com/hughy/pstack main
```

After each pull, review every row in `DIVERGENCE.md`. Diff the mirror for that skill between the commit the row records and the new one, and decide whether the reason still holds.

Do not edit files under `pstack/`. A local edit conflicts at the next pull, and `skill.sh` and `DIVERGENCE.md` assume the subtree matches the mirror. Put opinions in hworks files instead. For example, a delta in the router overrides a playbook, and a row in `adapters/pi.md` replaces a Cursor mechanism. Send install fixes to the mirror and content changes to upstream pstack. To follow a different mirror, fork it and pull from your fork's URL.

## Check a change

After you change hworks, run `scripts/check.sh`, which runs the Python script tests, the workflow tests, and the extension tests. Then:

- Run `scripts/skill.sh list` and confirm that the linked set matches the `DIVERGENCE.md` rows.
- Run `for l in skills/*; do [ -e "$l" ] || echo "broken: $l"; done` to find broken symlinks.
- Confirm that each skill's frontmatter `name` matches its directory name.
- Run `scripts/models.sh show` and confirm that each role has the model you expect.
- Run `/reload` in pi, then run the router on a small task that spawns at least one agent.
