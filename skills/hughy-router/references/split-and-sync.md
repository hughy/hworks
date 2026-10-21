# Split a branch and sync with its base

Read this from the hughy-router Ship route when a reviewed branch is too large for one PR, or a branch needs its base's new commits.

## Split a reviewed branch

The Build route decides one PR or a stack before building. Split after the fact only when a reviewed branch is too large anyway.

Skip the split when the PR already has human review threads or someone else pushed to the branch. Otherwise:

1. Record the reviewed tip: `ORIG=$(git rev-parse HEAD)`.
2. Build 2 to 4 layers from `ORIG`. Each layer merges alone, in order, and passes the gate. Keep tests with the code they cover, and keep each logical change in one layer.
3. Check that `git diff $ORIG <top layer>` is empty. The split moves code between commits and changes none of it.
4. Publish each layer as its own PR based on the previous layer's branch, following `global/AGENTS.md` Pull Requests.

Do not rerun review on each layer: the content was reviewed as a whole at `ORIG`, and step 3 proves the layers hold the same code. The layers are new commits the review ledger does not cover, so after step 3 record each one with `scripts/review-range.py record <layer task dir> <parent branch> <parent tip> <layer tip> split` before the pre-push review runs.

## Sync a branch with its base

For any PR:

1. `git fetch`, then `git merge origin/<base>`.
2. Resolve any conflicts and run the gate on the merged head.
3. Push without force. A merge keeps the push a fast-forward and keeps earlier review threads attached.

For stacked branches, merge the parent branch (or trunk, once the parent has merged) the same way, per `global/AGENTS.md` Pull Requests.

## Signed commits

A rebase or merge creates new commits, and they are signed only if signing is configured in that checkout. When the repo requires signed commits, run `git log --format='%h %G?' origin/<base>..HEAD` before the push. Any `N` is an unsigned commit; do not push until signing is configured and those commits are recreated signed.
