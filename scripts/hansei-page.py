#!/usr/bin/env python3
"""Render hansei findings JSON as one self-contained HTML page.

usage: hansei-page.py <findings.json> [-o page.html]

Writes to stdout unless -o is given. The page has all CSS and JS inline and makes no external
requests. Every string from the JSON is HTML-escaped. Each prompt renders in a <pre> with a
Copy button. The page quotes the operator's prompts: keep it out of repos.

Input schema (keys marked * are required; a missing one exits 2 naming it):
  {
    "title"*: "Hansei, 2026-10-13",
    "window"*: "2026-09-29 to 2026-10-13",
    "summary"*: "two or three sentences",
    "strengths": ["evidence-backed things that work; may be empty"],
    "findings"*: [
      {
        "title"*: "short claim",
        "owner"*: "you | system | both",
        "pattern"*: "what happens, with counts",
        "evidence": {"sessions": 7, "count": 19},
        "examples": [{"quote": "operator text", "context": "what the agent had said or done"}],
        "cost"*: "what it cost, observed (turns, corrections, re-explained context)",
        "suggestion"*: "the change in habit or system",
        "prompts"*: [{"label"*: "Queue it", "text"*: "copy-paste prompt"}]
      }
    ],
    "dropped": ["signal: reason it was dropped"],
    "previous": "optional: what changed since the last report"
  }
Findings render in the order given.
"""
import argparse
import json
import sys
from html import escape

REQUIRED = ["title", "window", "summary", "findings"]
FINDING_REQUIRED = ["title", "owner", "pattern", "cost", "suggestion", "prompts"]
PROMPT_REQUIRED = ["label", "text"]

CSS = """
:root { --fg: #1f2328; --muted: #59636e; --rule: #d8dee4; --accent: #0b5cad; --soft: #f6f8fa; }
* { box-sizing: border-box; }
body { margin: 0; background: #fff; color: var(--fg);
  font: 17px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
main { max-width: 46rem; margin: 0 auto; padding: 3rem 1.25rem 5rem; }
h1 { font-size: 1.9rem; line-height: 1.25; margin: 0 0 .25rem; }
h2 { font-size: 1.3rem; margin: 3rem 0 1rem; padding-top: 1rem; border-top: 1px solid var(--rule); }
h3 { font-size: 1.1rem; margin: 2.5rem 0 .5rem; }
.meta, .label { color: var(--muted); font-size: .9rem; }
.owner { display: inline-block; margin-left: .5rem; padding: 0 .45rem; border: 1px solid var(--accent);
  border-radius: 3px; color: var(--accent); font-size: .75rem; font-weight: 600; text-transform: uppercase;
  vertical-align: middle; letter-spacing: .03em; }
blockquote { margin: .75rem 0; padding: .1rem 0 .1rem 1rem; border-left: 3px solid var(--accent); }
blockquote p { margin: .2rem 0; }
blockquote .context { color: var(--muted); font-size: .9rem; }
table { border-collapse: collapse; margin: .5rem 0; font-size: .95rem; }
td, th { text-align: left; padding: .2rem 1rem .2rem 0; border-bottom: 1px solid var(--rule); }
.prompt { margin: .75rem 0 1.25rem; }
.prompt-head { display: flex; justify-content: space-between; align-items: center; }
pre { margin: .3rem 0 0; padding: .75rem 1rem; background: var(--soft); border: 1px solid var(--rule);
  border-radius: 4px; white-space: pre-wrap; word-break: break-word;
  font: 14px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
button.copy { font: inherit; font-size: .85rem; padding: .15rem .7rem; color: var(--accent); background: #fff;
  border: 1px solid var(--accent); border-radius: 3px; cursor: pointer; }
button.copy:hover { background: var(--soft); }
"""

JS = """
function selectText(el) {
  var r = document.createRange(); r.selectNodeContents(el);
  var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
}
document.querySelectorAll('button.copy').forEach(function (b) {
  b.addEventListener('click', function () {
    var pre = document.getElementById(b.getAttribute('data-target'));
    var done = function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy'; }, 1500); };
    var fallback = function () { selectText(pre); b.textContent = 'Selected: press Ctrl+C or Cmd+C'; };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(pre.textContent).then(done, fallback);
    } else { fallback(); }
  });
});
"""


class MissingKey(Exception):
    pass


def need(obj, key, where):
    if not isinstance(obj, dict) or key not in obj:
        raise MissingKey(f"{where}{key}")
    return obj[key]


def e(v):
    return escape(str(v), quote=True)


def para(text):
    return "".join(f"<p>{e(p)}</p>" for p in str(text).split("\n\n") if p.strip())


def render(data):
    for k in REQUIRED:
        need(data, k, "")
    for i, f in enumerate(data["findings"]):
        for k in FINDING_REQUIRED:
            need(f, k, f"findings[{i}].")
        for j, p in enumerate(f["prompts"]):
            for k in PROMPT_REQUIRED:
                need(p, k, f"findings[{i}].prompts[{j}].")

    out = ["<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f"<title>{e(data['title'])}</title><style>{CSS}</style></head><body><main>",
           f"<h1>{e(data['title'])}</h1>", f'<p class="meta">{e(data["window"])}</p>', para(data["summary"])]
    if data.get("previous"):
        out += ["<h2>Since last time</h2>", para(data["previous"])]
    if data.get("strengths"):
        out += ["<h2>What works</h2>", "<ul>", *(f"<li>{e(s)}</li>" for s in data["strengths"]), "</ul>"]
    out.append("<h2>Findings</h2>")
    if not data["findings"]:
        out.append("<p>No finding met the bar this time.</p>")
    for i, f in enumerate(data["findings"]):
        out.append(f'<h3>{i + 1}. {e(f["title"])}<span class="owner">{e(f["owner"])}</span></h3>')
        out.append(para(f["pattern"]))
        ev = f.get("evidence") or {}
        if ev:
            out.append("<table>" + "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in ev.items())
                       + "</table>")
        for ex in f.get("examples") or []:
            out.append(f'<blockquote><p>{e(ex.get("quote", ""))}</p>'
                       + (f'<p class="context">{e(ex["context"])}</p>' if ex.get("context") else "")
                       + "</blockquote>")
        out += ['<p class="label">Cost</p>', para(f["cost"]), '<p class="label">Suggestion</p>', para(f["suggestion"])]
        for j, p in enumerate(f["prompts"]):
            pid = f"prompt-{i}-{j}"
            out.append(f'<div class="prompt"><div class="prompt-head"><span class="label">{e(p["label"])}</span>'
                       f'<button class="copy" type="button" data-target="{pid}">Copy</button></div>'
                       f'<pre id="{pid}">{e(p["text"])}</pre></div>')
    if data.get("dropped"):
        out += ["<h2>Dropped</h2>", "<ul>", *(f"<li>{e(d)}</li>" for d in data["dropped"]), "</ul>"]
    out.append(f"</main><script>{JS}</script></body></html>")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 usage=argparse.SUPPRESS)
    ap.add_argument("findings")
    ap.add_argument("-o", "--output")
    args = ap.parse_args(argv)
    try:
        with open(args.findings) as f:
            data = json.load(f)
    except (OSError, ValueError) as err:
        print(f"hansei-page: {args.findings}: {err}", file=sys.stderr)
        sys.exit(2)
    try:
        html = render(data)
    except MissingKey as err:
        print(f"hansei-page: missing required key: {err}", file=sys.stderr)
        sys.exit(2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(html)
    else:
        sys.stdout.write(html)


if __name__ == "__main__":
    main()
