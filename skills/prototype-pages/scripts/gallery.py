#!/usr/bin/env python3
"""Turn a prototype manifest into a lettered gallery page, and optionally open it in a new browser window.

Any task that renders several prototype pages can use this. The manifest is JSON:

  {"title": "...", "description": "...",
   "prototypes": [{"id": "cards", "title": "...", "approach": "...",
                   "differences": ["..."], "features": ["..."],
                   "entry": "cards/index.html", "dir": "cards",
                   "baseline": false, "letter": "optional override"}]}

Paths are relative to the manifest and must stay inside its directory. Prototypes get letters A, B,
C... in order; a baseline entry is shown for comparison without a letter. Unless --no-stamp is given,
each prototype's pages get a small fixed badge with its letter that links back to the gallery: every
.html file under its dir when the manifest names one, otherwise only its entry page. Dirs must not
overlap. Restamping replaces the old badge.

--shots <dir> then screenshots each prototype with headless Chrome: its entry page plus the first
--inner-pages pages under its dir that the entry links to, at every --viewports size. --print-shots
lists those screenshots without running Chrome.
"""
import argparse
import html
import re
import urllib.parse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

BADGE_START, BADGE_END = "<!--prototype-badge-->", "<!--/prototype-badge-->"
CHROMIUM = ["Google Chrome", "Chromium", "Brave Browser", "Microsoft Edge", "Arc"]
HEADLESS = ["Google Chrome", "Chromium", "Brave Browser", "Microsoft Edge"]
HEADLESS_EXES = ["google-chrome", "chromium", "chromium-browser", "brave-browser", "microsoft-edge"]
SHOT_TIMEOUT = 60


def letter_for(n):
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def load(manifest_path):
    data = json.loads(Path(manifest_path).read_text())
    protos = data.get("prototypes")
    if not isinstance(protos, list) or not protos:
        raise ValueError("manifest needs a non-empty prototypes list")
    n = 0
    seen, labels = set(), set()
    for p in protos:
        for key in ("id", "title", "entry"):
            if not isinstance(p.get(key), str) or not p[key]:
                raise ValueError(f"prototype is missing {key}: {p}")
        if p["id"] in seen:
            raise ValueError(f"duplicate prototype id: {p['id']}")
        seen.add(p["id"])
        if p.get("baseline"):
            p["label"] = p.get("letter") or "Baseline"
        else:
            p["label"] = p.get("letter") or letter_for(n)
            n += 1
        if p["label"] in labels:
            raise ValueError(f"duplicate prototype letter: {p['label']}")
        labels.add(p["label"])
        p["anchor"] = f"p-{len(labels)}-" + re.sub(r"[^a-z0-9]+", "-", p["label"].lower()).strip("-")
        p.setdefault("approach", "")
        p.setdefault("differences", [])
        p.setdefault("features", [])
    return data


def anchor(p):
    return p["anchor"]


def url(path):
    """A relative filesystem path as a percent-encoded URL path."""
    return urllib.parse.quote(path.replace(os.sep, "/"), safe="/")


def inside(root, rel, what):
    """Resolve rel under root, rejecting absolute paths, escapes, and symlinks along the way."""
    if os.path.isabs(rel) or ".." in Path(rel).parts:
        raise ValueError(f"{what} must be a relative path inside the manifest directory: {rel}")
    path = root
    for part in Path(rel).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"{what} must not pass through a symlink: {path}")
    return path


def pages_for(root, p):
    """The pages a prototype's badge goes on."""
    if p.get("dir") is None:
        return [inside(root, p["entry"], "entry")]
    base = inside(root, p["dir"], "dir")
    if not base.is_dir():
        raise ValueError(f"prototype dir not found: {base}")
    return [page for page in sorted(base.rglob("*.html")) if not page.is_symlink()]


def badge(p, href):
    e = html.escape
    style = ("position:fixed;left:12px;bottom:12px;z-index:2147483647;display:flex;align-items:center;gap:8px;"
             "padding:5px 10px 5px 5px;border-radius:999px;background:#111;color:#fff;font:500 12px/1 system-ui,sans-serif;"
             "text-decoration:none;box-shadow:0 1px 4px rgba(0,0,0,.25);opacity:.9")
    dot = ("display:inline-grid;place-items:center;min-width:22px;height:22px;padding:0 4px;box-sizing:border-box;"
           "border-radius:999px;background:#fff;color:#111;font-weight:700")
    return (f'{BADGE_START}<a href="{e(href)}" title="Back to the prototype gallery" style="{style}">'
            f'<span style="{dot}">{e(p["label"])}</span>{e(p["title"])}</a>'
            f'<style>@media print{{a[title="Back to the prototype gallery"]{{display:none!important}}}}</style>{BADGE_END}')


def stamp(root, p, gallery):
    """Insert or replace the badge on the prototype's pages. Returns the page count."""
    count = 0
    for page in pages_for(root, p):
        if page.resolve() == gallery.resolve():
            continue
        text = page.read_text()
        start = text.find(BADGE_START)
        if start != -1:
            end = text.find(BADGE_END, start)
            text = text[:start] + text[end + len(BADGE_END):] if end != -1 else text[:start] + text[start + len(BADGE_START):]
        href = url(os.path.relpath(gallery, page.parent)) + "#" + anchor(p)
        tag = badge(p, href)
        i = text.lower().rfind("</body>")
        text = text[:i] + tag + "\n" + text[i:] if i != -1 else text + tag
        page.write_text(text)
        count += 1
    return count


CSS = """
:root { color-scheme: light; --fg: #1b1c1f; --muted: #6b6f76; --line: #e6e6ea; --soft: #f6f6f7; --accent: #2f5bd3;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; color: var(--fg); background: #fff; }
body { margin: 0; font-size: 15px; line-height: 1.55; }
main { max-width: 1120px; margin: 0 auto; padding: 40px 28px 120px; }
h1 { margin: 0 0 6px; font-size: 28px; font-weight: 600; letter-spacing: -0.01em; }
h2 { margin: 0; font-size: 20px; font-weight: 600; }
h3 { margin: 18px 0 6px; font-size: 13px; font-weight: 600; color: var(--muted); }
a { color: var(--accent); }
.lede { max-width: 760px; margin: 0 0 28px; color: #3c3f45; }
table { width: 100%; border-collapse: collapse; margin: 0 0 40px; font-size: 14px; }
th, td { padding: 9px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th { font-size: 12px; font-weight: 500; color: var(--muted); }
td.l { width: 44px; }
.letter { display: inline-grid; place-items: center; min-width: 28px; height: 28px; padding: 0 6px; box-sizing: border-box; border-radius: 6px;
  background: var(--fg); color: #fff; font-weight: 700; font-size: 14px; }
.letter.base { background: var(--soft); color: var(--muted); font-size: 11px; font-weight: 600; }
section.proto { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr); gap: 28px; padding: 32px 0; border-top: 1px solid var(--line); }
section.proto header { display: flex; align-items: center; gap: 12px; margin: 0 0 10px; }
section.proto p { margin: 0 0 8px; }
section.proto ul { margin: 0; padding-left: 20px; }
section.proto li { margin: 3px 0; }
.open { display: inline-block; margin-top: 14px; font-weight: 500; }
.frame { position: relative; height: 420px; overflow: hidden; border: 1px solid var(--line); border-radius: 8px; background: #fff; }
.frame iframe { position: absolute; top: 0; left: 0; width: 200%; height: 200%; border: 0; transform: scale(.5); transform-origin: 0 0; }
.frame a.cover { position: absolute; inset: 0; }
.compare { margin: 0 0 40px; }
.compare .bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 0 0 10px; font-size: 14px; }
.compare select { padding: 5px 8px; font: inherit; }
.compare .panes { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.compare iframe { width: 100%; height: 640px; border: 1px solid var(--line); border-radius: 8px; }
nav.jump { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 28px; }
nav.jump a { text-decoration: none; }
@media (max-width: 900px) { section.proto, .compare .panes { grid-template-columns: 1fr; } }
"""

COMPARE_JS = """
(() => {
  const [a, b] = document.querySelectorAll('.compare select');
  const [fa, fb] = document.querySelectorAll('.compare iframe');
  const sync = () => { fa.src = a.value; fb.src = b.value; };
  a.addEventListener('change', sync); b.addEventListener('change', sync); sync();
})();
"""


GENERATOR = '<meta name="generator" content="prototype-pages gallery">'


def gallery_html(data, out_dir, root):
    e = html.escape
    protos = data["prototypes"]
    rel = lambda p: url(os.path.relpath(root / p["entry"], out_dir))
    items = lambda xs: "".join(f"<li>{e(x)}</li>" for x in xs)
    letter = lambda p: f'<span class="letter{" base" if p.get("baseline") else ""}">{e(p["label"])}</span>'
    rows = "".join(
        f'<tr><td class="l">{letter(p)}</td><td><a href="#{anchor(p)}">{e(p["title"])}</a></td>'
        f'<td>{e(p["approach"].split(". ")[0].rstrip("."))}.</td><td>{e("; ".join(p["features"][:2]))}</td></tr>'
        for p in protos)
    sections = "".join(
        f'<section class="proto" id="{anchor(p)}"><div><header>{letter(p)}<h2>{e(p["title"])}</h2></header>'
        f'<p>{e(p["approach"])}</p>'
        + (f'<h3>How it differs</h3><ul>{items(p["differences"])}</ul>' if p["differences"] else "")
        + (f'<h3>What makes it more useful</h3><ul>{items(p["features"])}</ul>' if p["features"] else "")
        + f'<a class="open" href="{e(rel(p))}">Open {e(p["label"])} →</a></div>'
        f'<div class="frame"><iframe src="{e(rel(p))}" loading="lazy" tabindex="-1" title="Preview of {e(p["title"])}"></iframe>'
        f'<a class="cover" href="{e(rel(p))}" aria-label="Open {e(p["title"])}"></a></div></section>'
        for p in protos)
    options = lambda pick: "".join(
        f'<option value="{e(rel(p))}"{" selected" if i == pick else ""}>{e(p["label"])} · {e(p["title"])}</option>'
        for i, p in enumerate(protos))
    jump = "".join(f'<a href="#{anchor(p)}">{letter(p)}</a>' for p in protos)
    lettered = [p for p in protos if not p.get("baseline")]
    default = (f"{len(lettered)} prototypes, labelled {lettered[0]['label']} to {lettered[-1]['label']}. " if lettered else "") + \
        "Every page carries its label in the bottom-left corner; click it to come back here."
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">{GENERATOR}
<title>{e(data.get("title", "Prototypes"))}</title><style>{CSS}</style></head>
<body><main>
<h1>{e(data.get("title", "Prototypes"))}</h1>
<p class="lede">{e(data.get("description") or default)}</p>
<nav class="jump" aria-label="Prototypes">{jump}</nav>
<table><thead><tr><th></th><th>Prototype</th><th>Approach</th><th>Strengths</th></tr></thead><tbody>{rows}</tbody></table>
<div class="compare"><h2>Compare side by side</h2><div class="bar"><label>Left <select aria-label="Left prototype">{options(0)}</select></label>
<label>Right <select aria-label="Right prototype">{options(1 if len(protos) > 1 else 0)}</select></label></div>
<div class="panes"><iframe title="Left prototype"></iframe><iframe title="Right prototype"></iframe></div></div>
{sections}
</main><script>{COMPARE_JS}</script></body></html>
"""


def open_command(urls, browser=None, platform=sys.platform):
    """The command that opens urls as tabs of one new browser window."""
    if platform == "darwin":
        app = browser or next((b for b in CHROMIUM if Path(f"/Applications/{b}.app").exists()), None)
        if app in CHROMIUM:
            return ["open", "-na", app, "--args", "--new-window", *urls]
        if app:
            return ["open", "-a", app, *urls]
        return ["open", *urls]
    for exe in ([browser] if browser else ["google-chrome", "chromium", "chromium-browser", "brave-browser", "microsoft-edge"]):
        if exe and shutil.which(exe):
            return [exe, "--new-window", *urls]
    return ["xdg-open", urls[0]]


def chrome_path(chrome=None, platform=sys.platform):
    """The headless Chrome executable: --chrome when given, else the first installed Chromium browser."""
    if chrome:
        found = shutil.which(chrome)
        if not found:
            raise ValueError(f"browser executable not found: {chrome}")
        return found
    if platform == "darwin":
        for app in HEADLESS:
            exe = Path(f"/Applications/{app}.app/Contents/MacOS/{app}")
            if exe.is_file():
                return str(exe)
    for exe in HEADLESS_EXES:
        if shutil.which(exe):
            return shutil.which(exe)
    raise ValueError("no headless Chrome found; pass --chrome <executable>")


def parse_viewports(raw):
    sizes = []
    for v in raw.split(","):
        m = re.fullmatch(r"(\d+)x(\d+)", v.strip())
        if not m or not int(m[1]) or not int(m[2]):
            raise ValueError(f"bad viewport {v!r}; use WxH such as 1280x900")
        sizes.append((int(m[1]), int(m[2])))
    return sizes


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            parts = urllib.parse.urlsplit(value or "") if tag == "a" and key == "href" else None
            if parts and parts.path and not parts.scheme and not parts.netloc:
                self.paths.append(urllib.parse.unquote(parts.path))


def linked_paths(text):
    """Relative link paths of the <a> tags in an HTML page, in document order."""
    parser = LinkParser()
    parser.feed(text)
    parser.close()
    return parser.paths


def shot_pages(root, p, inner, gallery):
    """The entry page, then up to inner pages it owns other than the gallery: those the entry links to first, then the rest in path order."""
    entry = inside(root, p["entry"], "entry")
    if p.get("dir") is None or inner <= 0:
        return [entry]
    owned = {page.resolve(): page for page in pages_for(root, p)}
    owned.pop(entry.resolve(), None)
    owned.pop(gallery.resolve(), None)
    picked = []
    for rel in linked_paths(entry.read_text()):
        page = owned.get((entry.parent / rel).resolve())
        if page and page not in picked:
            picked.append(page)
    picked += [page for page in owned.values() if page not in picked]
    return [entry] + picked[:inner]


def shot_jobs(root, data, out_dir, sizes, inner, gallery):
    return [{"label": p["label"], "page": page, "rel": os.path.relpath(page, root), "size": f"{w}x{h}",
             "png": out_dir / f"{p['anchor']}-{n}-{w}x{h}.png"}
            for p in data["prototypes"] for n, page in enumerate(shot_pages(root, p, inner, gallery)) for w, h in sizes]


def frame_html(job):
    """A page that holds the prototype page in an iframe of exactly the viewport size. Headless Chrome's
    --window-size sets the outer window and keeps the layout at least 500px wide; an iframe's viewport is exact."""
    w, h = job["size"].split("x")
    return (f'<!DOCTYPE html><html><body style="margin:0;overflow:hidden"><iframe src="{html.escape(job["page"].as_uri())}"'
            f' style="display:block;border:0;width:{w}px;height:{h}px"></iframe></body></html>')


def shot_command(chrome, job, work):
    """The Chrome command that screenshots work/frame.html, written by take() from frame_html(job)."""
    w, h = job["size"].split("x")
    return [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
            f"--user-data-dir={work}/profile", f"--window-size={w},{h}", "--virtual-time-budget=3000",
            f"--screenshot={job['png']}", f"file://{urllib.parse.quote(str(work))}/frame.html"]


def take(chrome, job):
    """Screenshot one page with a fresh profile. Returns an error message, or None when the PNG was written."""
    job["png"].unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="prototype-shot-") as work:
        (Path(work) / "frame.html").write_text(frame_html(job))
        try:
            proc = subprocess.run(shot_command(chrome, job, work), capture_output=True, text=True, timeout=SHOT_TIMEOUT)
        except subprocess.TimeoutExpired:
            return f"timed out after {SHOT_TIMEOUT}s"
    if job["png"].is_file() and job["png"].stat().st_size:
        return None
    return (proc.stderr.strip().splitlines() or [f"no screenshot written, exit {proc.returncode}"])[-1]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("manifest")
    ap.add_argument("--out", help="gallery path (default: index.html beside the manifest)")
    ap.add_argument("--no-stamp", action="store_true", help="do not add letter badges to prototype pages")
    ap.add_argument("--open", action="store_true", help="open the gallery and every prototype in a new browser window")
    ap.add_argument("--print-open", action="store_true", help="print the open command instead of running it")
    ap.add_argument("--browser", help="browser application or executable name")
    ap.add_argument("--shots", metavar="DIR", help="screenshot every prototype into DIR with headless Chrome")
    ap.add_argument("--viewports", default="1280x900", help="comma-separated WxH sizes for --shots (default: 1280x900)")
    ap.add_argument("--inner-pages", type=int, default=1, help="pages besides the entry to shoot per prototype (default: 1)")
    ap.add_argument("--chrome", help="headless Chrome executable for --shots (default: first one found)")
    ap.add_argument("--print-shots", action="store_true", help="list the --shots screenshots without running Chrome")
    args = ap.parse_args(argv)
    try:
        manifest = Path(args.manifest).resolve()
        root = manifest.parent
        data = load(manifest)
        if args.print_shots and not args.shots:
            raise ValueError("--print-shots needs --shots <dir>")
        if args.shots:
            sizes = parse_viewports(args.viewports)
            chrome = None if args.print_shots else chrome_path(args.chrome)
        out = Path(os.path.abspath(args.out)) if args.out else root / "index.html"
        if out.is_symlink():
            raise ValueError(f"gallery output must not be a symlink: {out}")
        out = out.parent.resolve() / out.name
        owners = {}
        for p in data["prototypes"]:
            entry = inside(root, p["entry"], "entry")
            if entry.resolve() == out:
                raise ValueError(f"gallery would overwrite prototype entry {p['entry']}")
            if not entry.is_file():
                raise ValueError(f"prototype entry not found: {p['entry']}")
            for page in pages_for(root, p):
                if page in owners:
                    raise ValueError(f"prototypes {owners[page]} and {p['id']} would both stamp {page}; give them separate dirs")
                owners[page] = p["id"]
        # Rerunning replaces an earlier gallery; any other file there (an inner page of a flat layout) is someone's work.
        if out.exists() and GENERATOR not in out.read_text(errors="replace"):
            raise ValueError(f"gallery would overwrite {out}, which is not a gallery; choose another path with --out")
        page = gallery_html(data, out.parent, root)
        out.parent.mkdir(parents=True, exist_ok=True)
        stamped = 0 if args.no_stamp else sum(stamp(root, p, out) for p in data["prototypes"])
        out.write_text(page)
    except (OSError, ValueError) as error:
        print(f"gallery: {error}", file=sys.stderr)
        return 1
    print(f"{out.as_uri()}: {len(data['prototypes'])} prototypes, {stamped} pages stamped")
    for p in data["prototypes"]:
        print(f"  {p['label']:>8}  {p['title']}  {(root / p['entry']).as_uri()}")
    if args.shots:
        shots = Path(os.path.abspath(args.shots))
        jobs = shot_jobs(root, data, shots, sizes, args.inner_pages, out)
        if args.print_shots:
            for job in jobs:
                print(f"  shot {job['label']:>8}  {job['rel']}  {job['size']}  {job['png']}")
        else:
            shots.mkdir(parents=True, exist_ok=True)
            with ThreadPoolExecutor(max_workers=4) as pool:
                errors = list(pool.map(lambda job: take(chrome, job), jobs))
            for job, error in zip(jobs, errors):
                print(f"  shot {job['label']:>8}  {job['rel']}  {job['size']}  {error or job['png']}")
            failed = [f"{job['rel']} at {job['size']}: {error}" for job, error in zip(jobs, errors) if error]
            print(f"{len(jobs) - len(failed)} of {len(jobs)} screenshots in {shots}")
            if failed:
                for line in failed:
                    print(f"gallery: screenshot failed: {line}", file=sys.stderr)
                return 1
    if args.open or args.print_open:
        cmd = open_command([out.as_uri()] + [(root / p["entry"]).as_uri() for p in data["prototypes"]], args.browser)
        if args.print_open:
            print(" ".join(cmd))
        else:
            subprocess.run(cmd, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
