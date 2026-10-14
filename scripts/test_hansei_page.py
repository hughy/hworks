import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "hansei-page.py")

BAD = '<b>&"x\'</b>'


def findings(mark=BAD):
    return {
        "title": "T" + mark, "window": "W" + mark, "summary": "S" + mark, "strengths": ["G" + mark],
        "findings": [{
            "title": "F" + mark, "owner": "you" + mark, "pattern": "P" + mark,
            "evidence": {"sessions" + mark: 7, "count": "19" + mark},
            "examples": [{"quote": "Q" + mark, "context": "C" + mark}],
            "cost": "K" + mark, "suggestion": "U" + mark,
            "prompts": [{"label": "L" + mark, "text": "X" + mark}, {"label": "second", "text": "/skill:kaizen go"}],
        }, {
            "title": "Second finding", "owner": "system", "pattern": "p", "cost": "c", "suggestion": "s",
            "prompts": [{"label": "q", "text": "t"}],
        }],
        "dropped": ["D" + mark], "previous": "V" + mark,
    }


def render(data, env=None):
    return render_at(data, env)[0]


def render_at(data, env=None):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "f.json")
        with open(path, "w") as f:
            json.dump(data, f)
        p = subprocess.run([sys.executable, SCRIPT, path], capture_output=True, text=True,
                           env=dict(os.environ, **(env or {})))
        return p, os.path.abspath(path)


class Page(unittest.TestCase):
    def test_every_field_is_escaped(self):
        p = render(findings())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn(BAD, p.stdout)
        self.assertNotIn("<b>", p.stdout)
        esc = "&lt;b&gt;&amp;&quot;x&#x27;&lt;/b&gt;"
        for prefix in "TWSGFPKUCQLXDV":
            self.assertIn(prefix + esc, p.stdout, prefix)
        self.assertIn("you" + esc, p.stdout)
        self.assertIn("sessions" + esc, p.stdout)
        self.assertIn("19" + esc, p.stdout)

    def test_missing_required_key_exits_2_naming_it(self):
        for drop, name in (("title", "title"), ("findings", "findings")):
            data = findings()
            del data[drop]
            p = render(data)
            self.assertEqual(p.returncode, 2)
            self.assertIn(name, p.stderr)
        data = findings()
        del data["findings"][1]["cost"]
        p = render(data)
        self.assertEqual(p.returncode, 2)
        self.assertIn("findings[1].cost", p.stderr)
        data = findings()
        del data["findings"][0]["prompts"][1]["text"]
        p = render(data)
        self.assertEqual(p.returncode, 2)
        self.assertIn("findings[0].prompts[1].text", p.stderr)

    def test_prompts_get_copy_buttons(self):
        html = render(findings()).stdout
        pres = re.findall(r'<pre id="([^"]+)">', html)
        buttons = re.findall(r'<button class="copy" type="button" data-target="([^"]+)">Copy</button>', html)
        self.assertEqual(len(pres), 3)
        self.assertEqual(pres, buttons)
        self.assertIn("navigator.clipboard.writeText", html)
        self.assertIn("addRange", html)

    def test_findings_keep_order_and_owner(self):
        html = render(findings()).stdout
        self.assertLess(html.index("1. F&lt;b&gt;"), html.index("2. Second finding"))
        self.assertIn('<span class="owner">system</span>', html)

    def test_no_external_resources(self):
        html = render(findings(mark=" https://example.com/x.png")).stdout
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertFalse(re.search(r"""(?:src|href)\s*=\s*["']?\s*https?:""", html, re.I))
        self.assertFalse(re.search(r"url\(\s*['\"]?https?:", html, re.I))
        self.assertNotIn("<link", html)
        self.assertNotIn("<script src", html)

    def test_output_file(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = os.path.join(d, "f.json"), os.path.join(d, "p.html")
            with open(src, "w") as f:
                json.dump(findings("x"), f)
            p = subprocess.run([sys.executable, SCRIPT, src, "-o", out], capture_output=True, text=True)
            self.assertEqual((p.returncode, p.stdout), (0, ""))
            with open(out) as f:
                self.assertIn("<h1>Tx</h1>", f.read())


    def test_rendered_strings_are_redacted(self):
        token = "gh" + "p_" + "Zq9" * 12
        mail = "bob" + "@example.org"
        data = findings(mark="")
        data["title"] = f"T {token}"
        data["findings"][0]["examples"][0]["quote"] = f"mail {mail}"
        data["findings"][0]["prompts"][0]["text"] = f"use {token}"
        data["findings"][1]["title"] = "about ACME-" + "77"
        p = render(data, env={"HWORKS_REDACT": r"ACME-\d+"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn(token, p.stdout)
        self.assertNotIn(mail, p.stdout)
        self.assertNotIn("ACME-" + "77", p.stdout)
        self.assertIn("[redacted:github-token]", p.stdout)
        self.assertIn("mail [redacted:email]", p.stdout)
        self.assertIn('data-title="about [redacted:custom]"', p.stdout)

    def test_ids_default_by_position_and_explicit_ids_are_kept(self):
        html = render(findings()).stdout
        self.assertEqual(re.findall(r'class="pick-box"[^>]*data-id="([^"]+)"', html), ["H1", "H2"])
        data = findings()
        data["findings"][1]["id"] = "parser-retry"
        html = render(data).stdout
        self.assertEqual(re.findall(r'class="pick-box"[^>]*data-id="([^"]+)"', html), ["H1", "parser-retry"])

    def test_duplicate_id_exits_2_naming_it(self):
        data = findings()
        data["findings"][1]["id"] = "H1"
        p = render(data)
        self.assertEqual(p.returncode, 2)
        self.assertIn("duplicate finding id: findings[1].id H1", p.stderr)

    def test_plan_controls_carry_the_findings_path(self):
        p, path = render_at(findings())
        html = p.stdout
        self.assertEqual(len(re.findall(r'<input type="checkbox" class="pick-box"', html)), 2)
        self.assertEqual(len(re.findall(r'<textarea class="comment" id="comment-\d"', html)), 2)
        self.assertIn('<textarea id="note"', html)
        self.assertIn(f'<textarea id="plan" readonly data-source="{path}">', html)
        self.assertTrue(os.path.isabs(path))
        self.assertIn('data-title="Second finding"', html)
        self.assertIn('<button class="copy plan-copy" type="button" data-target="plan">Copy</button>', html)
        self.assertIn("el.select()", html)
        self.assertNotIn("localStorage", html)
        self.assertNotIn("fetch(", html)


    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_plan_message_composes_ticked_findings(self):
        html = render(findings()).stdout
        js = re.search(r"<script>(.*)</script>", html, re.S).group(1)
        stub = """
const els = {};
function mk(tag, attrs, extra) {
  return Object.assign({tagName: tag, getAttribute: k => attrs[k], addEventListener() {}, value: ''}, extra || {});
}
const boxes = [mk('INPUT', {'data-id': 'H1', 'data-title': 'First', 'data-comment': 'comment-0'}, {checked: true}),
               mk('INPUT', {'data-id': 'H2', 'data-title': 'Second', 'data-comment': 'comment-1'}, {checked: false}),
               mk('INPUT', {'data-id': 'H3', 'data-title': 'Third', 'data-comment': 'comment-2'}, {checked: true})];
els['comment-0'] = mk('TEXTAREA', {}, {value: ' keep the tests '});
els['comment-1'] = mk('TEXTAREA', {}, {value: 'ignored'});
els['comment-2'] = mk('TEXTAREA', {});
els.note = mk('TEXTAREA', {}, {value: 'overall note'});
els.plan = mk('TEXTAREA', {'data-source': '/abs/findings.json'});
globalThis.document = {getElementById: id => els[id],
  querySelectorAll: q => q === 'input.pick-box' ? boxes : []};
globalThis.window = {}; globalThis.navigator = {};
"""
        p = subprocess.run(["node", "-e", stub + js + "\nprocess.stdout.write(els.plan.value);"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "Hansei plan. Findings JSON: /abs/findings.json\n"
                         "Re-read each finding below by id from that file before acting on it.\n\n"
                         "[H1] First\nComment: keep the tests\n\n[H3] Third\n\nNote: overall note\n")


if __name__ == "__main__":
    unittest.main()
