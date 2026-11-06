---
name: prototype-pages
description: Generate several alternative prototype pages of a web page or HTML view (a dashboard, report, app screen, form, or landing page) from real data, label them A, B, C, and compare them in one gallery with screenshots. Use when asked for design variants, prototype pages, alternative layouts or styles, mockups to compare, or "N more prototypes" of an existing page.
---

# prototype-pages

Paths are relative to this skill's directory; pass them as absolute paths.

Prototypes are task output. Write them and everything they render in a scratch directory outside the repository. Commit only what makes the next round easier (a variant hook in the page's generator, say), and promote the chosen prototype in its own change.

The contract between whatever writes the pages and the gallery is a manifest, `prototypes.json`, beside the rendered pages:

```json
{"title": "...", "description": "optional lede",
 "prototypes": [{"id": "cards", "title": "Card grid", "approach": "One paragraph: the idea and who it serves.",
                 "differences": ["How it differs from the baseline"], "features": ["Why it is a better tool"],
                 "entry": "cards/index.html", "dir": "cards", "baseline": false}]}
```

## Steps

1. Pick the source of the pages. When the existing page renders from data, render the variants through its own generator: split data loading from presentation if needed, and prove the default output is unchanged by diffing a render before and after. With no generator, write static pages filled with real content from the live page or the brief, never placeholder text. Done when every variant shows the same data.
2. Write one variant per approach, numbered so the file order is the letter order. Each declares the manifest's `id`, `title`, `approach`, `differences`, and `features`, and differs from the others in structure (what the first screen answers), not only in colour. Include the current page as the baseline when there is one. For a filter box, facet chips, j/k row navigation, or tabs, inline `assets/kit.js` and `assets/kit.css`; their headers give the markup each part expects.
3. Render every variant into `<out>/<id>/` and write `<out>/prototypes.json`. Rendered private data stays local.
4. Run `scripts/gallery.py <out>/prototypes.json --open --shots <out>/shots --viewports 1280x900,390x844`.
5. Read every PNG it listed and fix what looks broken, including narrow-screen overflow. Done when every shot has been looked at and the run exits 0.
6. Reply with one line per letter: the approach, and the feature that makes it the better tool.

## Gallery

`scripts/gallery.py <manifest>` letters the prototypes in manifest order (a `baseline` entry is shown unlettered) and writes `index.html` beside the manifest: a summary table, a side-by-side compare, and one section per prototype with a live preview. It stamps each prototype's pages with a badge carrying its letter that links back: every page under `dir`, or only the entry when `dir` is omitted. Dirs must not overlap, and paths must stay inside the manifest directory without symlinks. Restamping replaces old badges and the old gallery, so rerun it after every render; it refuses to overwrite any other file at the gallery path, and `--out` picks another. `--no-stamp` leaves pages untouched. `--open` opens the gallery and every entry as tabs of one new browser window, and `--print-open` prints that command instead.

`--shots <dir>` screenshots each prototype with headless Chrome: its entry plus the first `--inner-pages` (default 1) pages under its `dir`, those the entry links to first and then the rest in path order, at each `--viewports` size (default `1280x900`). Each page loads in an iframe of exactly the viewport size, so media queries match. It prints one line per PNG and exits 1 when a page failed to render. `--print-shots` lists the planned shots without running Chrome; `--chrome <exe>` picks the browser. For measured overflow numbers instead of pictures, `../demo-video/scripts/shot.mjs` takes `file://<out>/` as its base URL with one `--path` per entry, but needs Playwright.

## Styles

Put colours in custom properties so a theme is a token override; a dark variant redefines the tokens and a few surfaces. `assets/kit.css` uses `--fg`, `--muted`, `--line`, `--soft`, `--bg`, `--accent`, and `--accent-soft`, with defaults that any `:root` rule overrides. Put helpers two or more variants use in a shared module, so each variant holds only its layout.
