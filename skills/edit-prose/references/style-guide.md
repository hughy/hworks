# Prose Style Guide

## Core rules

The "Prose" section of `global/AGENTS.md` is the canonical rule set. Read it and apply all of it. Do not restate it here; it changes there.

Two additions:

- Prefer the active voice unless the passive is clearly better: "The function returns a value", not "A value is returned by the function."
- Prefer two sentences to one joined with a semicolon.

## Content

Common review edits: what to say and what to leave out.

- Replace a vague noun with the thing itself. "The gap is documented" fails because the reader cannot tell which gap.
- Delete phrases that sound meaningful but say nothing: "unlocks new synergies", "sharpens the overlap".
- Name the exact entity. "The config contract" is ambiguous when two exist; "the config contract on the staging chain" is not. Name the product a reader knows, not its internal implementation.
- Make a doc stand alone, but do not restate known context. Summarize, then link.
- Write for busy engineers who skimmed the background doc. Prefer pseudocode, tables, and bullets to description.
- Include the mechanism a reader needs to follow the next point, stated once.
- Remove repeated points. Merge two sentences that make the same point.
- Watch for wording with legal or contractual weight, such as claims about compliance, licensing, or guarantees to customers.
- Do not present an option without team buy-in as the plan. Call it "_a_ proposal and not _the_ proposal".
- Leave out organization and staffing proposals unless asked.

## AI tropes

`global/AGENTS.md` already bans the most common tells (magic adverbs, "delve" vocabulary, negative parallelism, self-answered questions, gerund-fragment litanies, em dashes, bold-label bullets, signposted conclusions, "X is real"). Also cut these. Any one used once may be fine; cut repeats and clusters.

- Anaphora: several sentences in a row that open the same way ("They assume ... They assume ... They assume ...").
- Tricolons by reflex: lists of three, or stacked three-part parallel sentences, where the content does not have three parts.
- Trailing significance: an "-ing" clause that attaches meaning to a plain fact ("highlighting its importance", "reflecting broader trends").
- False ranges: "from X to Y" where X and Y are not ends of a real scale.
- Fragments as emphasis: one-line sentence fragments set apart for drama ("Openly. In a book.").
- A list disguised as prose: paragraphs that open "The first ... The second ... The third ...". Use a list.
- Fake suspense: "Here's the thing", "Here's the kicker", "Here's where it gets interesting".
- Teacher voice: "Let's break this down", "Let's unpack", "Think of it as ..." analogies the reader did not need.
- Sales framing: "Imagine a world where ...".
- Performed candor: "And yes, I'm biased", "This is not a rant; it's a diagnosis".
- Asserted obviousness: "The truth is simple", "History is clear". Show it instead.
- Inflated stakes: "will reshape everything", "defines the next era".
- Vague attribution: "experts say", "industry reports suggest". Name the source or cut the claim.
- Invented labels: coined terms like "the supervision paradox" used as if established.
- Fractal summaries: a summary at the start and end of every section.
- A metaphor repeated past its first use, or a run of historical analogies to borrow authority.
- One point restated many ways to seem thorough.
- "Despite these challenges, ..." as a reflex pivot to optimism.

## Preserve without alteration

- Code, variable names, function names, commands, and URLs.
- Technical terms. Do not substitute lay alternatives that lose precision.
- The author's meaning and substance.
- Markdown structure: headers, lists, code blocks, tables.
