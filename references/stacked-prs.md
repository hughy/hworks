# Stacked PRs

Stack dependent PRs with `gh stack` (the `github/gh-stack` extension). PRs are dependent when one needs the other's code, when both touch the same file (tests included), or when one changes behavior the other's tests assert. Before opening sibling PRs off trunk, compare their `git diff --name-only trunk...<branch>` lists and stack any overlap.

1. Branch each PR from its parent's branch, and the bottom one from trunk. Initialize local tracking with `gh stack init --base <trunk> <bottom branch> ... <top branch>`; always name trunk because the repo's default branch can differ.
2. Create each PR with `gh pr create --base <parent branch>`, the bottom one with `--base <trunk>`. Fill in each PR's template, then join them with `gh stack link --base <trunk> <bottom branch> ... <top branch>`. `gh stack submit` cannot set PR bodies non-interactively.
3. After linking, check each PR's base with `gh pr view <n> --json baseRefName`, and fix a mismatch with `gh pr edit <n> --base <branch>`. Record the stack number from `gh stack link`; removing the remote stack requires `gh stack unstack <number>`.
4. Rewrite stacked branches only through `gh stack rebase`, `gh stack sync`, and `gh stack push`, and only on your own stack branches. Never run raw `git rebase` or `git push --force` on them. Never run `gh stack merge`; the user lands the stack.
