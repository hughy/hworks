# Extension points

The engine names no document host, chat system, issue tracker, scheduler, or agent evidence toolset. Where a procedure needs one, it reads an extension file from the instance, `<instance>/extensions/<point>.md`, and follows it. An extension file is instructions for an agent: which tool to call, with what arguments, and what to do when the tool is missing in the current session.

A missing extension file is normal. Each procedure says what it does without one, and never guesses a system.

| Point | File | Read by | Supplies | Without it |
|---|---|---|---|---|
| `publisher` | `extensions/publisher.md` | `publish`, `digest` | How to publish a rendered HTML page to a slug, replace a later version, and read back its URL and version; whether new documents start private; the `Agent access` value for published documents | Render the HTML, report its path, and stop before publishing |
| `sources` | `extensions/sources/<kind>.md` | `digest` | For one source kind named in `DIGEST.md` (chat, documents, tracker, code host): how to list activity in a time window, how to link each item, and what marker to record | The digest lists the kind under coverage gaps |
| `evidence` | `extensions/evidence.md` | `retro`, `summarize-session` | For a repo and time window: how to collect agent friction and decision logs (corrections, defects caught by reviewers/tests/CI, autonomous decisions, guard blocks), agent tool-call reports, and operator messages from agent transcripts; for one session: where its friction notes live | Retro uses git history, pull requests, and instance sessions only, listing the other sources as coverage gaps; summarize-session takes friction only from the conversation |
| `tracker` | `extensions/tracker.md` | `brief`, `summarize-session` | How to read a tracker container registered as a `tracker` row in `DOCS.md`, and how to propose writes, each needing the user's approval | Skip the tracker comparison and say so |
| `access` | `extensions/access.md` | every procedure that reads `DOCS.md` | Extra `Agent access` values: one table row each with value, system, tool, and fallback | Only the engine's values in `templates/DOCS.md` apply |
| `scheduler` | `extensions/scheduler.md` | `templates/automation.md` | How to schedule an unattended launcher run on this instance's harness | Run the launcher by hand |
| `ship` | `extensions/ship.md` | every launcher that commits | Extra commit-message trailers, PR body lines, and a step to run after a PR opens | Plain commits and PRs |

## Rules

- An extension file belongs to its instance. Never copy one into hoffice.
- Extension files never hold credentials. They name the tool; the harness holds the auth.
- The publisher extension receives the `publisher` settings map from a digest's `DIGEST.md` unchanged. The engine never interprets it.
- A procedure that writes to an external system (publish, tracker writes) gets the user's yes for each write, unless the run is unattended and its prompt names the target as authorized.
