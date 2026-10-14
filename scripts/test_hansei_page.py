import json
import os
import re
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
            "prompts": [{"label": "L" + mark, "text": "X" + mark}, {"label": "second", "text": "/skill:retro go"}],
        }, {
            "title": "Second finding", "owner": "system", "pattern": "p", "cost": "c", "suggestion": "s",
            "prompts": [{"label": "q", "text": "t"}],
        }],
        "dropped": ["D" + mark], "previous": "V" + mark,
    }


def render(data):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "f.json")
        with open(path, "w") as f:
            json.dump(data, f)
        return subprocess.run([sys.executable, SCRIPT, path], capture_output=True, text=True)


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


if __name__ == "__main__":
    unittest.main()
