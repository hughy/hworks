# pstack mirror

This repo mirrors [`cursor/plugins/pstack`](https://github.com/cursor/plugins/tree/main/pstack) so pstack installs in pi, Claude Code, and Codex. `README.md` is upstream's with a short mirror preface above it. Cursor users should install upstream with `/add-plugin pstack`.

## What differs from upstream

- `skills/poteto-mode/SKILL.md` and `skills/make-bot-ui/SKILL.md`: frontmatter `name` uses the folder name (`poteto-mode`, `make-bot-ui`). pi's `/skill:` command stops at the first space, so the upstream names `Poteto Mode` and `Make Bot UI` can't be invoked.
- `agents-pi/`: upstream's two agents plus a `skills:` line. pi-subagents starts custom agents without the skill catalog, and `poteto-mode`, `how`, and `why` are hidden from it (`disable-model-invocation: true`).
- `.claude-plugin/` and `.codex-plugin/`: plugin manifests. Codex also reads `.claude-plugin/marketplace.json`.
- `README.md`: a mirror preface above Cursor's README.
- `MIRROR.md`: this file.

Everything else matches upstream byte for byte. The `upstream` branch holds the exact copy.

## Before you install

Skills run bundled scripts, for example `skills/poteto-mode/scripts/`. Read them first.

pstack was written for Cursor. Outside Cursor, these parts are untested:

- Skills that spawn subagents call Cursor's `Task` tool with `subagent_type: generalPurpose`. Your agent has to map that to its own subagent tool.
- `/setup-pstack` writes `~/.cursor/rules/pstack-models.mdc`, which only Cursor loads automatically. `swarm`, `arena`, and `interrogate` name the full path, so an agent elsewhere can read it. `how`, `why`, `architect`, and `reflect` name only `pstack-models.mdc`, so outside Cursor they likely fall back to their defaults. `poteto-mode` never names the file and keeps its own defaults.
- Default model names (grok, opus 5.5, sol) are Cursor slugs.

## Install

Clone the repo first. The examples use `~/dev/pstack`.

### pi

pstack loads as a skills folder plus an agents folder, which also works where pi packages are blocked.

1. Add the skills folder to `~/.pi/agent/settings.json`:

   ```json
   { "skills": ["~/dev/pstack/skills"] }
   ```

2. Link the agents (needs pi-subagents):

   ```bash
   mkdir -p ~/.pi/agent/agents
   ln -s ~/dev/pstack/agents-pi ~/.pi/agent/agents/pstack
   ```

3. Run `/reload` or start a new session. Check with `/skill:poteto-mode`.

If another skill already uses a pstack name, pi keeps the first one it finds and warns. Rename yours, or exclude pstack's with `"skills": ["~/dev/pstack/skills", "!~/dev/pstack/skills/<name>"]`.

### Claude Code

```bash
claude plugin marketplace add ~/dev/pstack
claude plugin install pstack@pstack
```

### Codex

```bash
codex plugin marketplace add ~/dev/pstack
```

Then install pstack from `/plugins`.

### Any agent with Agent Skills

```bash
npx skills add ~/dev/pstack
```

This copies the skills only, without the agents.

## Customize without editing the mirror

Every edit to a mirrored file can conflict at the next sync. Keep your opinions in a layer that sits on top:

- Put your own skills directory first in your harness's load order and point it at this repo second. pi keeps the first skill it finds for a name, so a skill in your directory shadows the pstack one.
- Pick which pstack skills load. Either exclude the ones you do not want (pi: `"!~/dev/pstack/skills/<name>"`), or keep an allowlist of symlinks into `skills/` and point every harness at that directory only. The allowlist works the same on every host; exclusions are per host.
- Write your own entry-point skill instead of editing `poteto-mode`. It can read any playbook under `skills/poteto-mode/playbooks/` by path and state where your rules differ.
- Pin models in your harness's own agent files (pi: `~/.pi/agent/agents/*.md` with `model:`). Only Cursor loads `pstack-models.mdc`.
- Keep one file that lists each pstack skill you shadow, skip, or copy, with the reason and the upstream commit you took it from. At each sync, diff upstream between that commit and the new head for those skills and port what matters.

Vendor this repo into your layer with `git subtree add --prefix pstack <path-or-url> main` and pull it with `git subtree pull` at each sync.

## Sync with upstream

`upstream` holds Cursor's files exactly. `main` is `upstream` plus the edits above. Never copy Cursor's files onto `main` directly.

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/cursor/plugins.git /tmp/cursor-plugins
git -C /tmp/cursor-plugins sparse-checkout set pstack
git switch upstream
rsync -a --delete --exclude .git --exclude MIRROR.md /tmp/cursor-plugins/pstack/ ./
git add -A
git commit -m "upstream: cursor/plugins/pstack @ $(git -C /tmp/cursor-plugins rev-parse --short HEAD)"
git switch main
git merge upstream
```

The rsync overwrites `README.md` on `upstream`. The merge into `main` keeps the preface.

If `agents/` changed, copy each file into `agents-pi/` again and re-add its `skills:` line. If a merge conflict touches a skill `name`, keep upstream's change and restore the folder-name form.
