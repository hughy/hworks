# Design docs and review comments

Full sentences and enough detail that an engineer who skimmed the background doc can follow without a meeting. No emoji, no humor.

## Structure

For a doc that proposes a solution to one problem:

1. A metadata table: created, last updated, status, authors, contributors.
2. TL;DR: one bolded line that names the problem and the tradeoff: "We have a tradeoff between running a separate sync service or disabling parallel writes."
3. Context: two to four short paragraphs a reader new to the area can follow. Link to the background doc instead of restating it.
4. Problem: the failure the doc prevents, and why it is hard. Put the one invariant that must hold in bold.
5. Criteria: a table of P0 and P1 requirements, each a testable statement ("A user cannot withdraw more than their balance").
6. Options: a summary table (option, pros, cons), then one section per option. Each option section shows the proposed changes (pseudocode for data structures and interfaces), a worked scenario if the option prevents a failure, then "Pros" and "Cons" bullet lists.
7. Recommended Solution: name the option in bold, then explain why it beats each alternative against the criteria.
8. Input: a reviewer table (reviewer, preferred option, comment).

## Habits

- Propose with "We can ...". Recommend with "We suggest adopting ...". Give a personal view with "in my view".
- Write "e.g.," and "i.e.," with the trailing comma, usually inside parentheses: "(e.g., S3, R2)".
- Italicize the single word that carries the logic: "must contain *all* entries", "the key is *not* in the set".
- Walk through a failure as numbered steps with a named actor and concrete numbers:

  > 1. Alice has a balance of 10.
  > 2. Alice requests a withdrawal of 9 and receives a signed receipt.
  > 3. Before the receipt is recorded, Alice requests a second withdrawal of 9.
  > 4. Both withdrawals succeed, and Alice withdraws 18 from a balance of 10.

- Put every identifier in code: `finalizeWithdrawal`, `RETRY_WINDOW`.
- Keep rejected and speculative options, labeled honestly: "As a thought experiment ...", "TBD: ...".
- State costs and limits plainly in the cons, with numbers when known: "write latency >2s".
- Use Title Case for section headings (Context, Problem, Proposed Solutions, Recommended Solution).
- Hedge only when unsure, and say what is unknown.
- Cut connective filler: "in the event that", "at the time of", "In this way". Use "if", "when", "at".
- Do not add bold to a short section that has no invariant to state.

## Review comments in someone else's doc

One to three sentences: a verdict, then the main drawback or condition. Frame them personally when it helps ("As I understand it", "in my view"), and name other docs by full title.

> The main drawbacks are the limited concurrency and slower writes. The overall simplification is worthwhile in my view.

> Option 2 does not support parallel writes. Option 1B is a clear improvement over option 1A.
