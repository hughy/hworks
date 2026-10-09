# Issues and PR descriptions

Brief and factual. These are read later by people without the conversation's context, so state the problem or change plainly. The "Linear Issues" and "Commits" sections of `~/AGENTS.md` also apply.

## Issues

- Four sentences or fewer for a small issue. State the problem and the acceptance criteria.
- Use concrete nouns: name the service, the module, the field. Put paths and identifiers in code.
- Put acceptance criteria under an `## Acceptance criteria` heading as a bullet list.

## PR descriptions

- Short. Lead with why the change is needed, then what it does.
- List mechanical changes as bullets when there are several.
- State constraints the reviewer must know: "Callers must not skip a block; the event loop enforces this."
- Follow the repo's PR template when one exists.

Examples of the length and level of detail:

> Unknown fields are ignored in API requests. This is dead code we can safely delete.

> We cannot filter by status once the record body is encrypted.
>
> This moves status filtering from SQL into application code:
> - Updating status reads, deserializes, and rewrites the record.
> - Filtering by status reads and deserializes each record.
>
> `list_expired` now matches expiration _equal_ to the given block. Callers must not skip a block.
