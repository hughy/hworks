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

`../../scripts/prototype-gallery.py <manifest> --open` letters the prototypes in manifest order (a `baseline` entry is shown unlettered), stamps every page under each `dir` with a badge carrying its letter that links back to the gallery, writes the gallery (`index.html` beside the manifest: summary table, side-by-side compare, one section per prototype with a live preview), and opens the gallery plus every entry as tabs of one new browser window. `--print-open` prints that command instead; `--no-stamp` leaves pages untouched. Restamping replaces old badges, so rerun it after every render.

## Steps

1. Find the existing generator and its data. Split it into a model (data loaded once) and presentation (data in, page out) if it is not split already, and prove the default output is unchanged by diffing a render before and after. Done when a variant can change layout without touching data loading.
2. Write one module per variant, numbered so the file order is the letter order. Each declares `id`, `title`, `approach`, `differences`, and `features`, and differs from the others in structure (what the first screen answers), not only in colour. Include the current page as the baseline.
3. Render every variant into `<out>/<id>/` and write the manifest. Keep output outside the source tree; rendered private data stays local.
4. Run the gallery with `--open`.
5. Screenshot each entry and one inner page with headless Chrome (`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --hide-scrollbars --window-size=1280,900 --screenshot=<png> <file-url>`), read the images, and fix what looks broken. `../demo-video/scripts/shot.mjs` adds overflow checks at several viewports. Done when every page has been looked at.
6. Reply with one line per letter: the approach, and the feature that makes it the better tool.

## Styles

Build variant CSS on the base stylesheet's custom properties (`--fg`, `--muted`, `--faint`, `--line`, `--soft`, `--bg`, `--accent`, `--accent-soft`), so a theme can be a token override (the dark variant redefines only tokens and a few surfaces). Put helpers two or more variants use in a shared module; it keeps each variant to its layout.

## hoffice dashboard

The worked example. `hoffice/scripts/lib/dashboard.mjs` holds the model and default pages; a variant module may export `meta`, `css` (appended to `baseCss`, or the whole sheet with `replaceCss`), `head`, `script`, `bodyClass`, `shell`, `index`, `project`, `doc`, and `pages` (extra pages). `ctx.parts` exposes the default page sections for recomposition. Variants live in `hoffice/prototypes/dashboard/`; `_shared.mjs` holds their helpers.

```
node hoffice/scripts/render-prototypes.mjs --instance <instance> --out /tmp/hoffice-prototypes --baseline hoffice/prototypes/dashboard
python3 scripts/prototype-gallery.py /tmp/hoffice-prototypes/prototypes.json --open
```

`render-dashboard.mjs --variant <module>` renders one variant. hoffice's `scripts/check.sh` rejects tracker and chat product names anywhere in hoffice, including CSS such as `linear-gradient`.
