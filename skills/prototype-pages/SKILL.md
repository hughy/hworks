---
name: prototype-pages
description: Generate several alternative prototype pages of a dashboard or other HTML view from real data, label them A, B, C, and compare them in one gallery opened in a new browser window. Use when asked for design variants, prototype pages, alternative layouts or styles, or "N more prototypes" of an existing page.
---

# prototype-pages

Paths are relative to this skill's directory; pass them as absolute paths.

The contract between a page generator and the gallery is a manifest, `prototypes.json`, beside the rendered pages:

```json
{"title": "...", "description": "optional lede",
 "prototypes": [{"id": "cards", "title": "Card grid", "approach": "One paragraph: the idea and who it serves.",
                 "differences": ["How it differs from the baseline"], "features": ["Why it is a better tool"],
                 "entry": "cards/index.html", "dir": "cards", "baseline": false}]}
```

`../../scripts/prototype-gallery.py <manifest> --open` letters the prototypes in manifest order (a `baseline` entry is shown unlettered), stamps each prototype's pages with a badge carrying its letter that links back to the gallery (every page under `dir`, or only the entry when `dir` is omitted; dirs must not overlap, and paths must stay inside the manifest directory without symlinks), writes the gallery (`index.html` beside the manifest: summary table, side-by-side compare, one section per prototype with a live preview), and opens the gallery plus every entry as tabs of one new browser window. `--print-open` prints that command instead; `--no-stamp` leaves pages untouched. Restamping replaces old badges, so rerun it after every render.

`--shots <dir>` then screenshots each prototype with headless Chrome: its entry plus the first `--inner-pages` (default 1) pages under its `dir` that the entry links to, at each `--viewports` size (default `1280x900`). It prints one line per PNG and exits 1 when any page failed to render. `--print-shots` lists the planned shots without running Chrome; `--chrome <exe>` picks the browser.

## Steps

1. Find the existing generator and its data. Split it into a model (data loaded once) and presentation (data in, page out) if it is not split already, and prove the default output is unchanged by diffing a render before and after. Done when a variant can change layout without touching data loading.
2. Write one module per variant in `$TASK_DIR/prototypes/` (from `../../scripts/task-dir.sh <slug>`), numbered so the file order is the letter order. Variants are task output: commit only the generator, data model, and hooks they need, and promote a chosen variant in its own change. Each declares `id`, `title`, `approach`, `differences`, and `features`, and differs from the others in structure (what the first screen answers), not only in colour. Include the current page as the baseline. For a filter box, facet chips, j/k row navigation, tabs, or age badges, inline `assets/prototype-kit.js` and `assets/prototype-kit.css` (a JS variant can read them by absolute path into its `script` and `css`); their headers give the markup each part expects.
3. Render every variant into `<out>/<id>/` and write the manifest. Keep output outside the source tree; rendered private data stays local.
4. Run the gallery with `--open --shots <out>/shots`, adding `--viewports 1280x900,390x844` to catch narrow-screen overflow.
5. Read every PNG it listed and fix what looks broken. Done when every shot has been looked at and the run exits 0. For measured overflow numbers, `../demo-video/scripts/shot.mjs` takes `file://<out>/` as its base URL with one `--path` per entry, but needs Playwright through `PLAYWRIGHT_FROM`.
6. Reply with one line per letter: the approach, and the feature that makes it the better tool.

## Styles

Build variant CSS on the base stylesheet's custom properties (`--fg`, `--muted`, `--faint`, `--line`, `--soft`, `--bg`, `--accent`, `--accent-soft`), so a theme can be a token override (a dark theme redefines only tokens and a few surfaces). `prototype-kit.css` uses the same tokens, with defaults any `:root` rule overrides. Put helpers two or more variants use in a shared module; it keeps each variant to its layout.

## hoffice dashboard

The worked example. `hoffice/scripts/lib/dashboard.mjs` holds the model and default pages; a variant module may export `meta`, `css` (appended to `baseCss`, or the whole sheet with `replaceCss`), `head`, `script`, `bodyClass`, `shell`, `index`, `project`, `doc`, and `pages` (extra pages). `ctx.parts` exposes the default page sections for recomposition. `render-prototypes.mjs` skips files starting with `_`, so a variants folder can keep shared helpers in `_shared.mjs`.

```
node hoffice/scripts/render-prototypes.mjs --instance <instance> --out /tmp/hoffice-prototypes --baseline "$TASK_DIR/prototypes"
python3 scripts/prototype-gallery.py /tmp/hoffice-prototypes/prototypes.json --open --shots /tmp/hoffice-prototypes/shots
```

`render-dashboard.mjs --variant <module>` renders one variant. hoffice's `scripts/check.sh` rejects tracker and chat product names anywhere in hoffice, including CSS such as `linear-gradient`.
