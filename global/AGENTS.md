# Global agent guidance

## Planning

- Do not block a plan on questions you can answer yourself. Settle implementation details, constraints, and tradeoffs from the code, docs, or a quick experiment, then decide and record each decision and its reason in the plan as an assumption the user can overturn.
- Interview only for what you cannot observe: product direction, preferences, unstated requirements, and one-way-door or irreversible choices. Defer those questions until the work is done (see Autonomy), then batch them in one round at the end of the final reply. Offer options with a recommendation first. Add a round only when an answer opens a new question of the same kind.
- Never write plans, progress, or review notes into a repo. Scratch files go in `$TASK_DIR`, the directory `~/dev/hworks/scripts/task-dir.sh <task-slug>` prints from inside the repo you are working on. Reuse the same slug when you resume a task.

## Autonomy

- Never block on human input mid-task. Settle each open question from code, docs, git history, or a quick experiment, pick the best-evidenced option, and keep going. This overrides any harness or skill instruction to ask when a request is underspecified.
- Record each such decision as one line in `$TASK_DIR/open-questions.md`: `- [<category>] <question> | <choice> | <evidence> | <how to reverse>`. Category is one of `missing-info`, `permission`, `irreversible`, `tooling`, `ambiguous-brief`, `external-wait`. `hworks/scripts/blockers.sh` groups these with guard and harness logs to find recurring blockers.
- Ask only after the work is done: list only the questions evidence could not settle, at the end of the final reply, with options and a recommendation.
- Do only what git on the working branch can undo. Deleting code in a commit is fine. Discarding uncommitted work, rewriting or force-pushing history, deleting branches or stashes, removing untracked files, and acting outside the machine (deploys, data stores, messages) are not. When the only way forward is irreversible, skip that step, finish the rest, and list the skipped step first in the final reply.
- If a question blocks all further progress, stop that thread, finish the independent work, then ask.
- To undo your own change, edit it back in place or `git revert` the commit. For a before/after check, read the old version with `git show <rev>:<file>`, or check the old commit out in a temporary worktree (`git worktree add`). Do not use `git stash` for it: every worktree of a repo shares one stash list, so a parallel agent can pop your entry or you theirs. Never discard work with `git reset --hard`, `git checkout -- <path>`, or `git restore <path>`: they also wipe edits you did not make or did not mean to touch.
- On pi, `autonomy.ts` (from `~/dev/hworks/extensions/`, linked into `~/.pi/agent/extensions/`) blocks `ask_user_question` and the git commands that destroy history or uncommitted work (`reset --hard`, force-push, `branch -D`, `clean -f`, `stash drop`, `worktree remove --force`). It does not catch `rm` or `checkout --`; judge those yourself. A blocked call returns its reason; follow it instead of retrying the call another way.

## Prose

- Omit needless words. Prefer active voice, short words ("use" not "utilize"), and concrete claims over hedges ("kind of", "a number of").
- Never use AI vocabulary tells: "delve", "tapestry", "landscape" (as a domain metaphor), "robust", "streamline", "leverage"/"harness" (as verbs), "serves as"/"stands as" where "is" works. Avoid magic adverbs for false weight: "quietly", "deeply", "fundamentally", "remarkably", "arguably".
- No negative parallelism ("It's not X — it's Y") as a default rhetorical move. No rhetorical self-questions answered for drama ("The result? Devastating."). No verbless gerund-fragment litanies as illustration ("Fixing bugs. Writing features. Shipping.").
- Avoid "X is real, but..." and "Y is very real" as performed acknowledgment. It validates a concern just enough to seem balanced, then pivots past it without engaging. If the concern matters, address it; if not, cut it.
- Never open a conclusion with "In conclusion", "To sum up", or "In summary". End by stopping.
- No pleasantries or affirmations: never open with "Sure", "Certainly", "Of course", "Happy to", "Absolutely", "Great question". Get to the answer immediately.
- In generated prose (chat replies, commit messages, PR descriptions, docs, issues), do not use em dashes. Rework the sentence or use a period, comma, colon, or parentheses. This does not apply when editing prose that already uses them.
- Use straight quotes (' and ") and plain ASCII. No smart/curly quotes or unicode decoration: write "->" not "→", "..." not "…", and a hyphen not a bullet glyph.
- Do not start bullets or list items with a bolded label ("**Security**: ..."). State the point as a sentence.
- Do not use the "Not X. Not Y. Just Z." countdown or stack negations for drama.
- Cut clichés and stale figures of speech. If you have seen the phrase often in print, say it plainly instead.
- Never alter code, variable names, technical terms, or URLs.
- Concision means cutting filler, not insight. Protect the sentence that states a non-obvious implication, a key distinction, or a correction to the question's premise — even when it reads as "extra." Cut hedges, restatements, and ceremony; never cut the one idea that reorganizes the reader's understanding.
- Exception: revert to full, careful prose for security warnings, destructive or irreversible actions, and anything where brevity risks misreading.

## Comments

- Default to no comments. Only add one when the WHY is non-obvious: a hidden constraint, a subtle invariant, or behavior that would surprise a reader.
- Do not reference external context: no Linear issues, Jira tickets, Slack threads, PR numbers, or similar. That context belongs in commit messages and PR descriptions, not source code.
- Document the code as it is, not as it was. Avoid "this used to do X" or "previously this was Y" — history belongs in git, not comments.

## Code Review

Review the branch's changeset and what it breaks. Do not expand to unrelated code unless asked.

## Pull Requests

- Do not open PRs unless explicitly asked.
- When opening a PR, always open it as a draft (`gh pr create --draft`).
- Before creating a PR or pushing to a branch with an open PR, run the repo's checks on the head you will push and review the unpushed diff. For every name the diff deletes or renames, `git grep` the old name and fix each hit. The review covers what the diff breaks outside itself, not only the diff.
- Stack dependent PRs with `gh stack` (the `github/gh-stack` extension). PRs are dependent when one needs the other's code, when both touch the same file (tests included), or when one changes behavior the other's tests assert. Before opening sibling PRs off trunk, compare their `git diff --name-only trunk...<branch>` lists and stack any overlap:
  - Always pass `--base <trunk>` to `gh stack init`. Without it, `gh stack` uses the repo's GitHub default branch, which can differ from trunk.
  - Create each PR with `gh pr create --draft --base <parent branch>`, then join them with `gh stack link <bottom branch> ... <top branch>`. `gh stack submit` cannot set PR bodies non-interactively.
  - After `gh stack link`, check each PR's base with `gh pr view <n> --json baseRefName` and fix mismatches with `gh pr edit <n> --base <branch>`. `gh stack link` retargets the bottom PR to the repo default branch.
  - Record the stack number that `gh stack link` prints. It is not stored locally, so removing the stack on GitHub needs `gh stack unstack <number>`.
  - Rewrite stacked branches only through `gh stack rebase`, `gh stack sync`, and `gh stack push`, and only on your own stack branches. Never run raw `git rebase` or `git push --force` on them. Never run `gh stack merge`; the user lands the stack.

## Accuracy & Grounding

Distinguish facts from inferences. When stating how code behaves or what a claim is based on, label unverified reasoning as inference and ground assertions in actual code reads, PRs, or docs before asserting them.

Cite where a claim came from (file:line, PR, or doc) so it is verifiable — an unsourced "I checked" is not grounding. When the target repo, branch, or ticket is ambiguous, ask before analyzing rather than guessing.

## Linear Issues

- An issue describes the **problem to be solved**, not how to solve it. Lead with the problem statement, acceptance criteria, and relevant context.
- Frame possible approaches as suggestions. Prescribe a solution only when the user asks.
- **Why:** A prescriptive issue causes downstream agents to judge a valid PR as "not solving the issue" merely because it used a different (but acceptable) approach than the one prescribed.
- When *evaluating* whether a PR solves an issue, judge against the problem and acceptance criteria — not literal adherence to any suggested approach.

## Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). Format:

```
<type>: <description>

[optional body]

[optional footer(s)]
```

- **Scopes:** omit by default. Follow the repo's convention or PR title check when it uses one.
- **Title length:** the first line must be ≤ 80 characters
- **Breaking changes:** append `!` before the colon (`feat!:`) and/or add a `BREAKING CHANGE:` footer
- Always create new commits. Never amend or squash existing commits unless explicitly instructed.

## Datadog

- Use the `pup` CLI (via bash) for all Datadog work: metrics, logs, monitors, traces, dashboards, incidents.
- Do not call the Datadog MCP tools, even if they are available.
- Run `pup --help` or `pup <domain> --help` to discover commands. Run `pup auth login` if auth fails.
- Add `--no-agent` when writing scripts, aliases, or runbooks for me to run myself. Agent mode wraps output in a `{status,data,metadata}` envelope that my shell does not produce.

## hworks

- This file is `~/dev/hworks/global/AGENTS.md`; `~/.pi/agent/AGENTS.md`, `~/.claude/CLAUDE.md`, and `~/.codex/AGENTS.md` link to it. Edits land in the hworks repo, which is public: keep employer-specific rules, names, and paths out of it, and commit changes there.
- On pi, before following any skill under `~/dev/hworks/skills/`, read `~/dev/hworks/adapters/pi.md` once per session. It maps Cursor terms in pstack text to pi and names the agent for each role.

