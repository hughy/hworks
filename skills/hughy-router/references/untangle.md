# Untangle a repo

Read this from the hughy-router Investigate route when asked what to refactor across a whole repo or subsystem, or to untangle one. The deliverable is a decision log of ranked fixes split into units; this phase changes no code. The Build route ships each unit, and Long run drives the program.

Adapted from `untangle-codebase` in caldoai/skills, paraphrased (its license is unstated).

## The question

Ask of every pair of pieces: should these change together? The code gets it wrong in three ways.

| Kind | Pieces that | Shapes |
|---|---|---|
| Hidden link | must change together, and nothing shows it | copied logic or values; a module reading state another sets; one feature split across folders by layer; a call order callers must know |
| Needless link | are tied, and change for different reasons | callers reaching into internals; stable code importing volatile code; a general function with a parameter only one caller understands; a shallow module whose interface moves with its internals |
| Surplus | have no reason of their own to change | pass-through wrappers; extension points and config nothing varies; dead code |

Also record every special case: an `if` for one value, a parameter for one caller, a swallowed error, a retry or sleep, a skipped test. Each is a requirement the design never absorbed, so read them as evidence for the redesign, not as items to fix one by one.

## 1. Gather evidence

Write each into `$TASK_DIR/untangle/` before reading code, so explorers start from the same facts:

- Tracker: open issues and PRs on the repo, and issues closed in the last 60 days with their titles. Planned work is not a finding; a problem that a closed issue's title claims fixed is a residual, labeled with that issue, and a closed issue's deliberate choice is not a problem.
- Docs: what the repo says must not change (public API, stored names, guarantees). A fix that breaks one is dropped, not filed.
- Skeleton: declarations without bodies, e.g. `rg -n '^\s*(func|type|class|def|interface|export) '`.
- Import graph between the repo's own packages, e.g. Go `go list -f '{{.ImportPath}}: {{join .Imports " "}}' ./...` filtered to the module path.
- Co-change: file pairs that change in the same commits over 180 days, with counts, among files that still exist. Pairs in different packages are hidden-link leads.

  ```sh
  git log --since=180.days.ago --no-merges --name-only --format=tformat:@ -- . ':!*_test.go' ':!*.md' \
  | python3 -c 'import sys,os,itertools,collections as c;n=c.Counter()
  for b in sys.stdin.read().split("@"):
   fs=sorted(f for f in set(b.split()) if os.path.exists(f))
   if 1<len(fs)<=12:n.update(itertools.combinations(fs,2))
  [print(k,*p) for p,k in n.most_common(60) if k>=3]'
  ```

- Special-case census: counts by file of swallowed errors, sleeps, skipped tests, and lint suppressions, production and test files counted apart, e.g. `rg -c 'time\.Sleep|//nolint|t\.Skip\(|_ = err\b' -g '!*_test.go'`. Keep the production total as a regression guard; its hits are often deliberate, so fixes may not lower it. Words like `retry` match prose and are noise.
- Agents' decision log: `../../../scripts/blockers.sh --log --cwd-match <repo>`.

Done when every file exists, or the reply says which source was unavailable.

## 2. List problems

Spawn 2 to 4 `explorer` runs, one slice of packages each, cut along the import graph so a leaf package sits with its importers. Each brief carries this file's absolute path, the slice, and the evidence dir, and asks for every problem in the slice as: kind, `file:line`, the evidence (code, co-change count, or import), and which pieces must change together or must not. An explorer changes nothing.

Done when every package is in exactly one slice and every explorer returned.

## 3. Verify

Explorer lists are leads: most entries describe the code accurately and still are not problems. For each slice, spawn a fresh `reviewer` with the slice's list, this file, and the evidence dir. It tries to refute each problem: the cited lines say what is claimed; every caller and copy is found, including tests, deploy files, and docs; the copies encode one rule, not similar syntax for different rules; the shape is not documented intent, a startup-frozen value, or a closed issue's deliberate choice. It keeps only what it cannot refute, drops when unsure, and gives the reason for each drop.

Done when every problem from step 2 is kept or dropped with a reason.

## 4. Group problems under fixes

Write `$TASK_DIR/untangle/log.md`. Above each group of problems, write the fix as if the system had known today's requirements from the start. Look for the one fix behind several problems; it often looks nothing like them. Test every fix: pieces that change together end up together, pieces that don't are untied, and each piece depends only on what changes less often than itself.

For each fix record the problems it removes, the special cases it removes from the census, what pins current behavior (a named existing test, or the characterization test to add), and the risk. Drop a problem an open issue or PR already covers, citing it, and drop a fix that breaks a surface the docs freeze. Rank fixes by problems removed per unit of risk, riskiest unknown first among equals.

Done when every problem kept in step 3 sits under a fix or is dropped with a reason.

## 5. Cut units

Split each fix into units. A unit merges alone, keeps trunk passing the gate, and pins behavior before structure moves. Size PRs by the Build route's one-PR-or-stack rule. Subtraction units go first. Units of one fix that cannot land apart form a stack.

State the program's exit predicate in checkable terms: a search per fix that must return nothing (a named import edge, a deleted symbol), new tests that pass, and the census not above its baseline. Then plan the issues with an issue-planning skill when one is installed, or draft them in the reply, one per fix with its units listed.

## 6. Re-audit

After each landed batch, rerun step 1 and the predicate's searches, and compare the census with the baseline. Stop when the predicate holds, or when a re-audit yields no fix that removes more than one problem.
