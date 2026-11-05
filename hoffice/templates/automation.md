# Unattended hoffice digest

One scheduled run per digest and cadence. A run renders the rolling page, publishes only when authorized, and opens a PR when material changes occur (draft by default; ready for review when `draft_pr: false`). Scheduling belongs to `<instance>/extensions/scheduler.md`: read it for the host's schedule, execution environment, authentication, and failure reporting. Without it, run `/hoffice-digest` by hand; do not invent a scheduling tool.

## Before scheduling

1. Install the engine's launchers and configure its home and instance roots as described in the engine README.md. The selected instance must have HOFFICE.md and a remote default branch.
2. Copy `<engine>/templates/digest-config.md` to `digests/<digest>/DIGEST.md` in the instance and fill in projects, source settings, timezone, cadence, patterns, and slug. Commit it to the instance default branch.
3. Supply `extensions/sources/<kind>.md` for each configured kind, plus publisher and scheduler extensions if used. Authenticate all tools in the scheduled environment, not just an interactive shell. Extension files name tools, never credentials.
4. Run `/hoffice-digest <digest> <cadence>` interactively. Verify source coverage, the rendered HTML, publication read-back when enabled, and the PR readiness configured by `draft_pr`. Resolve gaps before scheduling. The publisher extension supplies privacy and any sharing steps.
5. Follow the scheduler extension to run with fresh context and the prompt below. Match cadence and timezone to config. Verify the environment can resolve both engine and instance and write an isolated instance worktree. No particular agent or machine is required by the engine.

## Prompt

```text
/hoffice-digest <digest> <daily|weekly> --unattended

Do not ask questions. Take the conservative option and report Coverage gaps.
You are authorized to create or replace the publication at slug <slug>, and no other target.
Do not edit STATE.md or DOCS.md, or write to source systems.
Print publication URL or HTML path, PR URL (or quiet), window, source counts, and coverage gaps, then stop.
```

Remove the authorization sentence for render-only runs. An absent publisher extension always means render and stop before publication. A quiet run writes no digest or PR but updates the rolling page with a quiet note when a log exists.

## Review and recovery

- Read Coverage gaps first. Tool or auth failure for one source is a gap; every source unreadable fails the run.
- A missed run is covered by the next window up to `max_lookback_days`; a clamp is reported as a gap.
- The PR changes only `digests/<digest>/`: a dated file, plus config URL and first-published date on first publication. Review the file for detail; the PR body avoids backlinks to other changes or issues.
- Apply useful STATE.md and DOCS.md proposals separately after review. The unattended run never applies them.
- Merge accepted digests to keep the default branch complete. Open digest PRs already contribute to the next window and rolling log. Closing an unmerged PR drops it from the next run's refs; that period may then be covered again. Close stale PRs instead of leaving them open indefinitely.
