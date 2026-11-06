"""The prototype kit script works on a bare page in headless Chrome."""
import html
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
ASSETS = SKILL / "assets"

spec = importlib.util.spec_from_file_location("prototype_gallery", SKILL / "scripts" / "gallery.py")
gallery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gallery)


def chrome():
    try:
        return gallery.chrome_path()
    except ValueError:
        return None


class PrototypeKitTest(unittest.TestCase):
    @unittest.skipUnless(chrome(), "no headless Chrome")
    def test_script_filters_and_selects_a_tab_on_a_bare_page(self):
        page = f"""<!DOCTYPE html><html><head><style>{(ASSETS / "kit.css").read_text()}</style></head><body>
<input data-filter value="beta"><span data-count></span>
<div data-group id="g1"><p data-search="alpha" id="a">alpha</p></div><div data-group id="g2"><p data-search="beta" id="b">beta</p></div>
<nav class="tabs"><a href="#one">One</a><a href="#two">Two</a></nav>
<div class="panel" id="two"><p data-nav id="n2">hidden tab</p></div><div class="panel" id="one"><p data-nav id="n1">shown tab</p></div>
<script>{(ASSETS / "kit.js").read_text()}</script>
<script>document.body.dispatchEvent(new KeyboardEvent('keydown', {{key: 'j', bubbles: true}}));</script></body></html>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.html"
            path.write_text(page)
            result = subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={tmp}/profile",
                                     "--virtual-time-budget=2000", "--dump-dom", path.as_uri()], capture_output=True, text=True, timeout=60)
        dom = result.stdout
        self.assertIn('<span data-count="">1</span>', dom, result.stderr[-500:])
        self.assertIn('id="g1" hidden=""', dom)
        self.assertIn('id="a" hidden=""', dom)
        self.assertIn('<p data-search="beta" id="b">', dom)
        self.assertIn('<a href="#one" aria-selected="true">', dom)
        self.assertIn('class="panel on" id="one"', dom)
        self.assertIn('id="n1" class="cursor"', dom)
        self.assertNotIn('id="n2" class="cursor"', dom)

    @unittest.skipUnless(chrome(), "no headless Chrome")
    def test_keys_leave_form_fields_alone_and_follow_the_filter(self):
        page = f"""<!DOCTYPE html><html><head><style>{(ASSETS / "kit.css").read_text()}</style></head><body>
<input data-filter><textarea id="t"></textarea><button data-facet="due-soon=yes" id="f">Due</button>
<p data-nav data-search="alpha" id="a"><a href="#alpha">alpha</a></p><p data-nav data-search="beta" data-due-soon="yes" id="b"><a href="#beta">beta</a></p>
<pre id="out"></pre><script>{(ASSETS / "kit.js").read_text()}</script>
<script>
const key = (el, k) => el.dispatchEvent(new KeyboardEvent('keydown', {{key: k, bubbles: true, cancelable: true}}));
const out = {{}}, t = document.getElementById('t'), box = document.querySelector('[data-filter]');
t.focus(); out.slashPrevented = !key(t, '/'); out.active = document.activeElement.id;
t.blur(); key(document.body, 'j'); out.first = document.querySelector('.cursor')?.id;
box.value = 'beta'; box.dispatchEvent(new Event('input')); box.blur();
key(document.body, 'Enter'); out.hashAfterHiddenEnter = location.hash;
key(document.body, 'j'); out.afterFilter = [...document.querySelectorAll('.cursor')].map(e => e.id);
box.value = ''; box.dispatchEvent(new Event('input'));
out.afterClear = [...document.querySelectorAll('.cursor')].map(e => e.id);
document.getElementById('f').click(); out.facetHidesA = document.getElementById('a').hidden; out.facetKeepsB = !document.getElementById('b').hidden;
document.getElementById('out').textContent = JSON.stringify(out);
</script></body></html>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.html"
            path.write_text(page)
            result = subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={tmp}/profile",
                                     "--virtual-time-budget=2000", "--dump-dom", path.as_uri()], capture_output=True, text=True, timeout=60)
        out = json.loads(html.unescape(result.stdout.split('<pre id="out">')[1].split("</pre>")[0]))
        self.assertEqual(out, {"slashPrevented": False, "active": "t", "first": "a", "hashAfterHiddenEnter": "",
                               "afterFilter": ["b"], "afterClear": ["b"], "facetHidesA": True, "facetKeepsB": True})


if __name__ == "__main__":
    unittest.main()
