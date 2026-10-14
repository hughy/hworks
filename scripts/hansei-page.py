#!/usr/bin/env python3
"""Render hansei findings JSON as one self-contained HTML page.

usage: hansei-page.py <findings.json> [-o page.html]

Writes to stdout unless -o is given. The page has all CSS and JS inline, makes no external
requests, and keeps no state. Every string from the JSON is redacted with operator-signals.py's
redact() (including HWORKS_REDACT, read from adapters/local/*.env as there) and HTML-escaped.
Each prompt renders in a <pre> with a Copy button. The page quotes the operator's prompts: keep
it out of repos.

Plan hand-back: each finding has a checkbox and a comment box, and the page has an overall
note. A Plan section composes, as the operator types, one message to paste into any agent: the
absolute path of the findings JSON the page was built from, each ticked finding as
"[<id>] <title>" with its comment, then the note. Its Copy button falls back to selecting the
read-only plan text when the clipboard is denied. skills/hansei/SKILL.md says how an agent
handles the message.

Input schema (keys marked * are required; a missing one exits 2 naming it):
  {
    "title"*: "Hansei, 2026-10-13",
    "window"*: "2026-09-29 to 2026-10-13",
    "summary"*: "two or three sentences",
    "strengths": ["evidence-backed things that work; may be empty"],
    "findings"*: [
      {
        "id": "H1 (default H<n> by position; ids must be unique, a duplicate exits 2 naming it)",
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
import importlib.util
import json
import os
import sys
from html import escape

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("operator_signals", os.path.join(HERE, "operator-signals.py"))
osig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(osig)

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
.fid { margin-left: .5rem; color: var(--muted); font-size: .8rem; font-weight: 400; vertical-align: middle; }
.pick { display: block; margin: 1rem 0 .3rem; font-weight: 600; }
textarea { width: 100%; min-height: 3.5rem; padding: .5rem .75rem; border: 1px solid var(--rule); border-radius: 4px;
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
textarea#plan { min-height: 10rem; background: var(--soft);
  font: 14px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
"""

JS = """
function selectText(el) {
  var r = document.createRange(); r.selectNodeContents(el);
  var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
}
document.querySelectorAll('button.copy').forEach(function (b) {
  b.addEventListener('click', function () {
    var el = document.getElementById(b.getAttribute('data-target'));
    var isField = el.tagName === 'TEXTAREA';
    var done = function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy'; }, 1500); };
    var fallback = function () {
      if (isField) { el.focus(); el.select(); } else { selectText(el); }
      b.textContent = 'Selected: press Ctrl+C or Cmd+C';
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(isField ? el.value : el.textContent).then(done, fallback);
    } else { fallback(); }
  });
});
var plan = document.getElementById('plan');
function composePlan() {
  var lines = ['Hansei plan. Findings JSON: ' + plan.getAttribute('data-source'),
    'Re-read each finding below by id from that file before acting on it.', ''];
  var picked = 0;
  document.querySelectorAll('input.pick-box').forEach(function (c) {
    if (!c.checked) { return; }
    picked++;
    lines.push('[' + c.getAttribute('data-id') + '] ' + c.getAttribute('data-title'));
    var note = document.getElementById(c.getAttribute('data-comment')).value.trim();
    if (note) { lines.push('Comment: ' + note); }
    lines.push('');
  });
  if (!picked) { lines.push('(no finding ticked)', ''); }
  var overall = document.getElementById('note').value.trim();
  if (overall) { lines.push('Note: ' + overall); }
  plan.value = lines.join('\\n').trim() + '\\n';
}
document.querySelectorAll('input.pick-box, textarea.comment, textarea#note').forEach(function (el) {
  el.addEventListener('input', composePlan); el.addEventListener('change', composePlan);
});
composePlan();
"""


class MissingKey(Exception):
    pass


class DuplicateId(Exception):
    pass


def need(obj, key, where):
    if not isinstance(obj, dict) or key not in obj:
        raise MissingKey(f"{where}{key}")
    return obj[key]


REDACT_EXTRA = None


def e(v):
    return escape(osig.redact(str(v), REDACT_EXTRA), quote=True)


def para(text):
    return "".join(f"<p>{e(p)}</p>" for p in str(text).split("\n\n") if p.strip())


def render(data, source=""):
    for k in REQUIRED:
        need(data, k, "")
    for i, f in enumerate(data["findings"]):
        for k in FINDING_REQUIRED:
            need(f, k, f"findings[{i}].")
        for j, p in enumerate(f["prompts"]):
            for k in PROMPT_REQUIRED:
                need(p, k, f"findings[{i}].prompts[{j}].")
    ids = []
    for i, f in enumerate(data["findings"]):
        fid = str(f.get("id") or f"H{i + 1}")
        if fid in ids:
            raise DuplicateId(f"findings[{i}].id {fid}")
        ids.append(fid)

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
        out.append(f'<h3>{i + 1}. {e(f["title"])}<span class="owner">{e(f["owner"])}</span>'
                   f'<span class="fid">{e(ids[i])}</span></h3>')
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
        out.append(f'<label class="pick"><input type="checkbox" class="pick-box" id="pick-{i}" data-id="{e(ids[i])}" '
                   f'data-title="{e(f["title"])}" data-comment="comment-{i}"> Add [{e(ids[i])}] to the plan</label>'
                   f'<textarea class="comment" id="comment-{i}" aria-label="Comment on {e(ids[i])}" '
                   f'placeholder="Optional comment for the agent"></textarea>')
    if data.get("dropped"):
        out += ["<h2>Dropped</h2>", "<ul>", *(f"<li>{e(d)}</li>" for d in data["dropped"]), "</ul>"]
    out += ["<h2>Plan</h2>",
            "<p>Tick findings above, comment on them, add a note, then copy the plan into an agent.</p>",
            '<label class="pick" for="note">Note</label>',
            '<textarea id="note" placeholder="Optional note for the whole plan"></textarea>',
            '<div class="prompt"><div class="prompt-head"><span class="label">Plan message</span>'
            '<button class="copy plan-copy" type="button" data-target="plan">Copy</button></div>'
            f'<textarea id="plan" readonly data-source="{e(source)}"></textarea></div>']
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
    global REDACT_EXTRA
    osig.load_env_files()
    REDACT_EXTRA = osig.redact_pattern()
    try:
        html = render(data, os.path.abspath(args.findings))
    except MissingKey as err:
        print(f"hansei-page: missing required key: {err}", file=sys.stderr)
        sys.exit(2)
    except DuplicateId as err:
        print(f"hansei-page: duplicate finding id: {err}", file=sys.stderr)
        sys.exit(2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(html)
    else:
        sys.stdout.write(html)


if __name__ == "__main__":
    main()
