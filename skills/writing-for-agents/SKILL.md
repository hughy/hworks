---
name: writing-for-agents
description: Write or edit a document an agent reads - a skill, an agent prompt, an AGENTS.md, or a doc an agent reaches by a pointer. Use when creating or changing one, or when judging whether a line in one earns its place.
license: MIT (adapted from mattpocock/skills; see LICENSE)
---

# Writing for agents

Adapted from the `writing-for-agents` skill in mattpocock/skills (commit 49dd158, MIT, see `LICENSE`). Prose style follows `global/AGENTS.md`. This file covers what makes an agent-facing document change behavior. The hworks bar applies to every line: it earns its place by changing what a run does, shown by an observed failure or a measured gain (README, Rationale).

## Pointers

A pointer is text always in context that names material out of context and the condition for reaching it: a skill's description, a line in `AGENTS.md` naming a file, a path in hughy-router. Its wording, not its target, decides when the agent reaches the material. When a needed file goes unread, sharpen the pointer first, and inline the material only if that fails.

A pointer states what the material is and lists the branches that should trigger it. A branch is a distinct case; synonyms for one case are one branch. A pointer loads every turn, so prune it hardest:

- Put the trigger word first.
- Write one trigger per branch.
- Cut what the body already says about itself.

## Two costs

Context load is what always-loaded text costs: `AGENTS.md`, skill descriptions, agent prompts, and tool schemas spend tokens and attention every turn, whether they fire or not. `scripts/kaizen-tokens.py` measures it in token-turns.

Cognitive load is what the operator pays to remember which documents exist and when to reach for each. Spend it where human judgment matters. hughy-router is the single entry point so the operator remembers one name.

## Model-invoked, command, or read by path

pi lists every skill's name and description in the system prompt unless the frontmatter sets `disable-model-invocation: true`. `/skill:<name>` still works then. A description is required either way (at most 1024 characters); pi does not load a skill without one.

- Make a skill model-invoked when the agent must reach it on its own. Write its description as a pointer with trigger branches.
- Make it a command (`disable-model-invocation: true`) when only the operator starts it. Its description is one human-facing line with no trigger list.
- Have another skill read it by path when a router or workflow needs it: hughy-router reads skills as `../<name>/SKILL.md`, which works for both kinds. Subagents load only the skills their agent file lists (`skills:` in `agents/*.md`), so a brief that needs another file names its absolute path.

An agent prompt in `agents/*.md` loads into every run of that role. Treat each line as context load for every child.

## Hierarchy

A document holds steps (what the agent does, in order) and reference (rules and facts it consults on demand). Place each piece by how soon the agent needs it:

1. A step in the file.
2. Reference in the file.
3. Reference in a separate file (`references/<name>.md`), reached by a pointer.

Keep in the file what every branch needs, and move out what only some branches reach. Too little moved out buries the steps; too much hides what the agent needs. Keep a concept's definition, rules, and caveats under one heading. A document that is too long even with every line live gets split by branch or by sequence.

## Completion criteria

End every step on a criterion the agent can check: "the command you ran fails on the reported symptom", not "understand the bug". A vague criterion invites premature completion, and visible later steps pull harder. Sharpen the criterion first. Only when it stays fuzzy and you observe the rush, move the later steps behind a real context boundary, a subagent or a hand-off. A step later in the same context hides nothing.

Demand drives legwork: "every caller accounted for" forces more digging than "list the callers". The strongest criteria are checkable and exhaustive.

## Leading words

A leading word is a compact concept the model already knows (tracer bullet, red, tight loop, frontier) that anchors a region of behavior in one token. Repeat the word, never its definition. Prefer an existing word to a coined one: a coined word costs definition tokens and recruits no priors. Collapse triads and sentence-long gestures into one word ("fast, deterministic, low-overhead" -> tight). A word too weak to beat the default ("be thorough") is a no-op; replace it with a stronger word, not more words.

## Prohibitions

A prohibition names the behavior it bans. Prefer stating the target behavior ("write one-line comments"). Keep a prohibition for a hard guardrail with no positive form, and pair it with the target. This is a heuristic from the source, not measured in hworks: before rewriting a rule file on its strength, run the rewrite and compare.

## Pruning

- Keep one meaning in one place. Point at `global/AGENTS.md` instead of restating it.
- Treat the environment as a source of truth: `--help` output, config files, the directory layout. A document that restates it is a cache, worth its load only for what the agent cannot find by looking: an unwritten convention, the reason behind a choice, a gotcha.
- Hunt no-ops sentence by sentence. A line the model already obeys changes nothing. The test is relative to the model's default, so settle a dispute by running the document with and without the line. Delete the whole sentence, not words from it. `DIVERGENCE.md` drops pstack principles on this test.
- Prune as you edit. Stale layers settle because adding feels safe and deleting feels risky, so each edit checks nearby lines for ones that went stale.

## Before you finish

- The frontmatter has a `name` matching the directory and a `description`.
- Every path the document names resolves from where it is read. `scripts/kaizen-setup.py` reports guidance paths that resolve to nothing.
- The commit message names the failure or gain behind each new line. The document does not.
