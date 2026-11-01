---
name: disk-cleanup
description: Free disk space by removing mux worktrees untouched for 3+ days and old forge/anvil state, then clearing the go and npm caches. Use for "/skill:disk-cleanup", "free disk space", or "clean up old worktrees".
---

# Disk cleanup

1. Run `bash <skill-dir>/cleanup.sh` from the current repo. It lists what it flags and deletes nothing:
   - Linked git worktrees under `~/.mux` with no file changed in 3+ days (working tree and its git admin dir). The worktree you run from is never flagged.
   - Entries in `~/.foundry/anvil/tmp` and `~/.foundry/cache/rpc` older than 3 days.
2. Run `bash <skill-dir>/cleanup.sh --delete`. It removes the flagged items, runs `go clean -cache -testcache -modcache` and `npm cache clean --force`, and prints free space before and after.
3. Report the space freed and any worktrees it kept.

Worktree removal uses `git worktree remove` without `--force`, so git keeps any worktree with uncommitted or untracked files, and every branch survives. Do not force-remove a kept worktree; list it for the operator.

`STALE_DAYS`, `MUX_ROOT`, and `FOUNDRY_ROOT` override the defaults.
