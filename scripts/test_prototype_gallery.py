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
                           "baseline": i == 0, **({"dir": pid} if i else {})})
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
        self.assertIn("3 prototypes, 5 pages stamped", result.stdout)
        html = (self.root / "index.html").read_text()
        self.assertNotIn(BAD, html)
        self.assertIn("Gallery &lt;b&gt;&amp;&quot;x&#x27;&lt;/b&gt;", html)
        for pid, anchor in [("base", "p-1-baseline"), ("one", "p-2-a"), ("two", "p-3-b")]:
            self.assertIn(f'href="{pid}/index.html"', html)
            self.assertIn(f'id="{anchor}"', html)
        self.assertIn("2 prototypes, labelled A to B", html)

    def test_stamping_is_idempotent_and_links_back_to_the_gallery(self):
        for _ in range(2):
            self.assertEqual(self.run_cli().returncode, 0)
        page = (self.root / "one" / "sub" / "page.html").read_text()
        self.assertEqual(page.count(gallery.BADGE_START), 1)
        self.assertIn('href="../../index.html#p-2-a"', page)
        self.assertLess(page.index(gallery.BADGE_END), page.index("</BODY>"))
        self.assertNotIn(BAD, page)
        top = (self.root / "two" / "index.html").read_text()
        self.assertIn('href="../index.html#p-3-b"', top)
        self.assertIn(">B</span>", top)

    def test_without_a_dir_only_the_entry_page_is_stamped(self):
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertIn(gallery.BADGE_START, (self.root / "base" / "index.html").read_text())
        self.assertNotIn(gallery.BADGE_START, (self.root / "base" / "sub" / "page.html").read_text())

    def write_manifest(self, protos, **extra):
        self.manifest.write_text(json.dumps({"prototypes": protos, **extra}))

    def test_flat_layout_keeps_each_entry_its_own_letter_and_overlapping_dirs_fail(self):
        for name in ("a.html", "b.html"):
            (self.root / name).write_text("<html><body></body></html>")
        self.write_manifest([{"id": "a", "title": "a", "entry": "a.html"}, {"id": "b", "title": "b", "entry": "b.html"}])
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertIn(">A</span>", (self.root / "a.html").read_text())
        self.assertIn(">B</span>", (self.root / "b.html").read_text())
        self.write_manifest([{"id": "a", "title": "a", "entry": "one/index.html", "dir": "one"},
                             {"id": "b", "title": "b", "entry": "one/sub/page.html", "dir": "one/sub"}])
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn("would both stamp", result.stderr)

    def test_paths_outside_the_manifest_directory_or_through_symlinks_fail_before_writing(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(outside))
        (outside / "index.html").write_text("<html><body>victim</body></html>")
        os.symlink(outside, self.root / "link")
        cases = [
            ({"id": "x", "title": "t", "entry": "../" + outside.name + "/index.html"}, "inside the manifest directory"),
            ({"id": "x", "title": "t", "entry": str(outside / "index.html")}, "inside the manifest directory"),
            ({"id": "x", "title": "t", "entry": "link/index.html"}, "symlink"),
            ({"id": "x", "title": "t", "entry": "one/index.html", "dir": "link"}, "symlink"),
        ]
        for proto, message in cases:
            self.write_manifest([proto])
            result = self.run_cli()
            self.assertEqual(result.returncode, 1, proto)
            self.assertIn(message, result.stderr)
        self.assertEqual((outside / "index.html").read_text(), "<html><body>victim</body></html>")
        self.write_manifest([{"id": "x", "title": "t", "entry": "one/index.html"}])
        os.symlink(outside / "index.html", self.root / "index.html")
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn("must not be a symlink", result.stderr)
        self.assertEqual((outside / "index.html").read_text(), "<html><body>victim</body></html>")

    def test_custom_letters_cannot_inject_markup_and_must_be_unique(self):
        evil = 'x"><svg/onload=alert(1)>'
        self.write_manifest([{"id": "x", "title": "t", "entry": "one/index.html", "dir": "one", "letter": evil}])
        self.assertEqual(self.run_cli().returncode, 0)
        for page in (self.root / "index.html", self.root / "one" / "index.html"):
            self.assertNotIn("<svg", page.read_text())
        self.write_manifest([{"id": "x", "title": "t", "entry": "one/index.html", "letter": "Q"},
                             {"id": "y", "title": "t", "entry": "two/index.html", "letter": "Q"}])
        self.assertIn("duplicate prototype letter", self.run_cli().stderr)

    def test_baseline_only_manifest_renders(self):
        for extra in ({}, {"description": "Only the baseline."}):
            self.write_manifest([{"id": "b", "title": "b", "entry": "base/index.html", "baseline": True}], **extra)
            result = self.run_cli()
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_paths_with_url_metacharacters_are_percent_encoded(self):
        d = self.root / "design #1?%"
        d.mkdir()
        (d / "index.html").write_text("<html><body></body></html>")
        self.write_manifest([{"id": "x", "title": "t", "entry": "design #1?%/index.html", "dir": "design #1?%"}])
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertIn('href="design%20%231%3F%25/index.html"', (self.root / "index.html").read_text())

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
