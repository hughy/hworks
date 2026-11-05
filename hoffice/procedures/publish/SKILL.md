---
name: publish
description: Draft, render, and publish a project document, then record the verified URL and version in its source and DOCS.md.
---

# Publish

Input: instance root, project, and slug. The caller owns discovery and git. Resolve templates and scripts from the engine root, not the instance.

1. Read the instance's `AGENTS.md` and the project's `README.md`, `STATE.md`, `DOCS.md`, and relevant decisions. Read `extensions/access.md` if present before interpreting extra `Agent access` values; otherwise only `public`, `git`, `local`, and `mirror` apply.
2. Load `projects/<project>/published/<slug>.md`. If absent, ask what it should contain and draft from `<engine>/templates/published.md` using the sources above. Set `source_state_revision` to the instance's `git rev-parse HEAD`. Get approval of a new draft before continuing.
3. Check every frontmatter field from the template exists. Require nonempty `title`, `project`, `type`, `audience`, `authority`, and `slug`, with `slug` matching the requested slug. Require a nonnegative integer `version`; a previously published document also needs `url`, `first_published`, and `last_published`. The slug is permanent after first publication; a different slug means a new document.
4. Scan for credentials, keys, customer or personal data, and internal hostnames the audience should not have. List any findings and stop until the user removes them or confirms they may be shared. Never publish `STATE.md`, sessions, or `local` documents directly; draft publishable content in `published/` first. A repo's implementation docs belong in that repo, not here; register their published result in `DOCS.md` instead.
5. Render with `node <engine>/scripts/render-published.mjs <absolute source.md> <absolute out.html>`. Create an output directory outside tracked content first. Keep dated, self-contained prose, with the as-of date in the first paragraph. Use the renderer's house style: paper background, system fonts, one accent, no external fonts, scripts, hero, or filler sections.
6. Read `<instance>/extensions/publisher.md`. If missing, report the HTML path and stop before publishing or changing bookkeeping. Otherwise follow it for publishing, replacing a version, privacy, and URL/version read-back. For a replacement, show what changed since `last_published` and get a yes before writing. Every external write needs approval, unless an unattended prompt explicitly authorizes this target. If declined, stop without retrying. Read back the URL and version; do not infer a version by incrementing a local number.
7. Only after verified success, write `url`, `version`, `last_published` (today), and `first_published` if null to the source frontmatter. Add or update the matching `DOCS.md` row: `Doc` = title, `Type` and `Authority` from frontmatter, `Link` = verified URL, `Owner` = user, `Agent access` = publisher extension's value, `Last checked` = today, `Notes` = `source: published/<slug>.md, v<version>`. Extra access values must be defined by `extensions/access.md`; do not guess one.
8. Return the HTML path, URL, version, changed files, and any sharing step the publisher requires. Hand git back to the caller.
