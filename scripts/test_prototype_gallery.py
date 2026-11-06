import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "prototype-gallery.py")
spec = importlib.util.spec_from_file_location("prototype_gallery", SCRIPT)
gallery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gallery)

BAD = '<b>&"x\'</b>'


class PrototypeGalleryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        protos = []
        for i, pid in enumerate(["base", "one", "two"]):
            (self.root / pid / "sub").mkdir(parents=True)
            (self.root / pid / "index.html").write_text(f"<html><body><h1>{pid}</h1></body></html>")
            (self.root / pid / "sub" / "page.html").write_text("<html><BODY>page</BODY></html>")
            protos.append({"id": pid, "title": f"{pid} {BAD}", "approach": f"First {BAD}. Second.",
                           "differences": [f"diff {BAD}"], "features": [f"feat {BAD}"], "entry": f"{pid}/index.html",
                           "baseline": i == 0})
        self.manifest = self.root / "prototypes.json"
        self.manifest.write_text(json.dumps({"title": f"Gallery {BAD}", "prototypes": protos}))

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, str(self.manifest), *args], capture_output=True, text=True)

    def test_letters_skip_the_baseline_and_continue_past_z(self):
        self.assertEqual([gallery.letter_for(n) for n in (0, 1, 25, 26, 27, 701, 702)], ["A", "B", "Z", "AA", "AB", "ZZ", "AAA"])
        data = gallery.load(self.manifest)
        self.assertEqual([p["label"] for p in data["prototypes"]], ["Baseline", "A", "B"])

    def test_gallery_escapes_content_and_links_every_prototype(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("3 prototypes, 6 pages stamped", result.stdout)
        html = (self.root / "index.html").read_text()
        self.assertNotIn(BAD, html)
        self.assertIn("Gallery &lt;b&gt;&amp;&quot;x&#x27;&lt;/b&gt;", html)
        for pid, anchor in [("base", "p-baseline"), ("one", "p-a"), ("two", "p-b")]:
            self.assertIn(f'href="{pid}/index.html"', html)
            self.assertIn(f'id="{anchor}"', html)
        self.assertIn("2 prototypes, labelled A to B", html)

    def test_stamping_is_idempotent_and_links_back_to_the_gallery(self):
        for _ in range(2):
            self.assertEqual(self.run_cli().returncode, 0)
        page = (self.root / "one" / "sub" / "page.html").read_text()
        self.assertEqual(page.count(gallery.BADGE_START), 1)
        self.assertIn('href="../../index.html#p-a"', page)
        self.assertLess(page.index(gallery.BADGE_END), page.index("</BODY>"))
        self.assertNotIn(BAD, page)
        top = (self.root / "two" / "index.html").read_text()
        self.assertIn('href="../index.html#p-b"', top)
        self.assertIn(">B</span>", top)

    def test_no_stamp_leaves_pages_alone(self):
        before = (self.root / "one" / "index.html").read_text()
        self.assertEqual(self.run_cli("--no-stamp").returncode, 0)
        self.assertEqual((self.root / "one" / "index.html").read_text(), before)

    def test_print_open_lists_gallery_then_prototypes_in_one_new_window(self):
        result = self.run_cli("--print-open", "--browser", "Google Chrome")
        self.assertEqual(result.returncode, 0, result.stderr)
        last = result.stdout.strip().splitlines()[-1]
        if sys.platform != "darwin":
            self.skipTest("the new-window command is platform specific")
        self.assertTrue(last.startswith("open -na Google Chrome --args --new-window file://"), last)
        urls = [w for w in last.split() if w.startswith("file://")]
        self.assertEqual([u.rsplit("/", 2)[-2:] for u in urls][1:], [["base", "index.html"], ["one", "index.html"], ["two", "index.html"]])
        self.assertTrue(urls[0].endswith("/index.html") and "/base/" not in urls[0])

    def test_open_command_falls_back_per_platform(self):
        self.assertEqual(gallery.open_command(["u"], "Safari", "darwin"), ["open", "-a", "Safari", "u"])
        self.assertEqual(gallery.open_command(["u"], "Brave Browser", "darwin")[:5], ["open", "-na", "Brave Browser", "--args", "--new-window"])
        self.assertEqual(gallery.open_command(["u", "v"], "no-such-browser-xyz", "linux"), ["xdg-open", "u"])

    def test_bad_manifests_fail_without_writing(self):
        cases = [
            ({"prototypes": []}, "non-empty prototypes"),
            ({"prototypes": [{"id": "x", "title": "t"}]}, "missing entry"),
            ({"prototypes": [{"id": "x", "title": "t", "entry": "missing.html"}]}, "entry not found"),
            ({"prototypes": [{"id": "x", "title": "t", "entry": "one/index.html"}] * 2}, "duplicate prototype id"),
        ]
        for data, message in cases:
            self.manifest.write_text(json.dumps(data))
            result = self.run_cli()
            self.assertEqual(result.returncode, 1, data)
            self.assertIn(message, result.stderr)
        self.assertFalse((self.root / "index.html").exists())
        self.manifest.write_text(json.dumps({"prototypes": [{"id": "x", "title": "t", "entry": "one/index.html"}]}))
        result = self.run_cli("--out", str(self.root / "one" / "index.html"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("would overwrite", result.stderr)


if __name__ == "__main__":
    unittest.main()
