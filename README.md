# hworks

A personal layer over the [pstack](./pstack/) mirror. `pstack/` is a git subtree of the mirror; edits to it go to the mirror. Everything hworks owns lives outside it.

- `skills/hughy-mode/` is the entry point. Six routes, each starting from a goal, effort, and verify brief, with pstack playbooks read by path as references and the hworks deltas applied.
- `skills/review-loop/` and `workflows/review-loop.js` run a `coder` change and its review to a verdict as one pi-subagents workflow; `scripts/review-loop-args.sh` builds its args from the effort level. `node --test workflows/*.test.js` checks the loop logic.
- `skills/edit-prose/` drafts and edits prose: a style guide that defers to the `~/AGENTS.md` prose rules, plus guides for design docs, issues, and PR descriptions.
- `skills/<name>` symlinks are the allowlist of pstack skills and principles that load. Some serve hughy-mode routes. Others (`bro`, `teach`, `swarm`, `correct`, and the verification-skill pair) are commands to invoke directly, useful or not depending on the harness. `scripts/skill.sh enable|disable|list <name>` manages them.
- `agents/` sets the prompt and tool scope per role for pi-subagents: `coder`, `reviewer`, `explorer`, `synthesizer`.
- `extensions/autonomy.ts` is a pi extension that blocks `ask_user_question` and git commands that destroy history or uncommitted work, returning a redirect to the model. It enforces the Autonomy section of `~/AGENTS.md`. `/autonomy off` relaxes it for one session; `PI_AUTONOMY=0` disables it. `node --experimental-strip-types extensions/autonomy.test.mts` checks the classifier and the log.
- `scripts/blockers.sh [--since 7d] [--json]` reports where runs blocked: guard blocks and asks logged by `autonomy.ts`, subagent `contact_supervisor` decision requests, idle, failed, or paused subagents, categorized `open-questions.md` entries, and an optional harness audit log. Feed the output to `/skill:correct` to fix recurring classes.
- `adapters/pi.md` maps Cursor-specific terms in pstack skills to pi.
- `models.conf` and `scripts/models.sh` hold the model roster. A profile names a model for each agent role and sets two slots that hughy-mode reads for per-call overrides: `review2` (the second reviewer) and `exhaustive` (the `coder` model at exhaustive effort). `models.sh <profile>` writes the role models to pi settings as `subagents.agentOverrides.<role>.model` and leaves the agent files untouched; `models.sh show` prints the active profile. Profiles: `inherit` (session model, the default) and `anthropic`.
- `DIVERGENCE.md` records every skill not linked, with the reason and the pstack mirror commit.
- `CUSTOMIZING.md` covers forking hworks into your own layer, adding agent roles and model profiles, and writing an overlay repo.

## Rationale

hworks starts from the harness as it ships: a frontier model, its tools and subagents, `~/AGENTS.md`, and a brief that states the goal, the effort, and how to verify. Additions stay small and earn their place by changing what a run does. When a model handles something well from a plain brief, hworks leaves it alone.

- pstack is a reference library. A pstack skill loads when it adds behavior a plain brief does not get, or when it is useful on its own as a command. `DIVERGENCE.md` records every exclusion. Playbooks are read by path when a run stalls, the change is high-stakes, or it runs unattended. They are not scripts.
- `~/AGENTS.md` owns prose, comments, commits, and PR rules. hworks points at it and does not restate it.
- Multi-day work with several concurrent writers belongs to a multi-agent coordinator when the harness has one. hworks does not rebuild one. Below that scale, `progress.md` and git are the record.
- Model names live in `models.conf` and pi settings. Skills name roles and slots, so a new model or a provider outage is one profile switch.

## Why a layer

pstack's skills reference each other by name (`/poteto-mode` appears 120 times across `skills/`, `agents/`, and `docs/`), and eight skills call Cursor's `Task` tool. Editing those files in place risks a merge conflict at every upstream sync. A separate directory of symlinks costs nothing at sync time. The mirror stays a byte-exact input, and this repo holds every opinion.

## Install (pi)

```json
{ "skills": ["~/dev/hworks/skills"] }
```

```bash
ln -s ~/dev/hworks/agents ~/.pi/agent/agents/hworks
ln -s ~/dev/hworks/extensions/autonomy.ts ~/.pi/agent/extensions/autonomy.ts
```

Then `/reload` and start a task with `/skill:hughy-mode <task>`. The skills root follows symlinks, and `skillPath: ../skills` in each agent file resolves the same links.

pi-subagents resolves one model per launch and fails when it is unavailable. When a provider is down, apply another profile, for example `scripts/models.sh inherit`, then `/reload`.

Claude Code and Codex load only `skills/` through the plugin manifests. The agent files are pi-specific, so on those harnesses `hughy-mode`'s roles map to the harness's own subagent and `adapters/pi.md` does not apply. Symlink following on those harnesses is unverified.

## Local overlays

Two gitignored paths hold machine- or employer-specific setup without changing tracked files:

- `models.d/*.conf`: extra profiles in the `models.conf` format. `models.sh` reads them alongside `models.conf`.
- `adapters/local/`: extra adapter notes, for example a mapping from the generic terms in hughy-mode ("a PR-tracking tool", "the closest available model") to one harness's tool names. hughy-mode reads every file here after `adapters/pi.md`. A `blockers.env` here is sourced by `scripts/blockers.sh`, for example to set `HWORKS_HARNESS_AUDIT_LOG`.

[`CUSTOMIZING.md`](./CUSTOMIZING.md#overlays) lists the terms an adapter maps and the layout of an overlay repo.

## Resync

```bash
git subtree pull --squash --prefix pstack https://github.com/hughy/pstack main
```

Then, for each row in `DIVERGENCE.md`, diff the mirror between the recorded commit and the new one for that skill and decide whether the reason still holds. `scripts/skill.sh list` shows what is linked.
