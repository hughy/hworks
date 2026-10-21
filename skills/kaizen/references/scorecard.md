# Sampled scorecards

Score 5 to 10 sessions, chosen in this order:

1. The sessions behind the PRs with the most rework in `kaizen-prs.py` `outcomes`.
2. The sessions behind any PR closed unmerged.
3. The sessions behind the most-cited `friction.md` entries.
4. Two sessions with clean outcomes (merged, no rework, no friction) as a success baseline.

Score each dimension with its evidence (session path and entry timestamp, PR URL, check name, or review), a confidence (high, medium, low), or Not assessable when the data is missing:

- Spec adherence: solved the request, broke no constraint, added no scope.
- Test value: reused existing coverage, added no redundant or low-value test.
- Redundancy: repeated searches, reads, retries, tests, or edits.
- Efficiency: tool choice, batching, delegation, retries.
- Judgment: followed through, surfaced blockers, took no unsafe workaround.
- Code and PR quality: correctness, CI, review, rework.
- Delivery time: agent time against CI, reviewer, and human wait, from `kaizen-prs.py` `time`.
- Human intervention: corrections, repeated instructions, rescue, from `operator-signals.py` and `friction.md`.

Write them to `$TASK_DIR/scorecards-<date>.md`. A scorecard is evidence for a finding or a success pattern, cited by session; it is never a score to track or a target. The Privacy rules in `../SKILL.md` apply.
