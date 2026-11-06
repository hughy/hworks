import importlib.util
import json
import shutil
import zlib
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

def _has_chrome():
    try:
        return bool(gallery.chrome_path())
    except ValueError:
        return False


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


class PrototypeShotsTest(unittest.TestCase):
    """--shots, run against a stand-in Chrome that writes the --screenshot file, or fails for pages under two/."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for pid in ("one", "two"):
            (self.root / pid / "a").mkdir(parents=True)
            (self.root / pid / "a" / "first.html").write_text("<html><body>first</body></html>")
            (self.root / pid / "z.html").write_text("<html><body>linked</body></html>")
            (self.root / pid / "index.html").write_text('<html><body><a href="https://x/y.html">x</a><a href = \'z.html#top\'>z</a></body></html>')
        self.manifest = self.root / "prototypes.json"
        self.manifest.write_text(json.dumps({"prototypes": [
            {"id": "one", "title": "one", "entry": "one/index.html", "dir": "one"},
            {"id": "two", "title": "two", "entry": "two/index.html"}]}))
        self.chrome = self.root / "fake-chrome"
        self.chrome.write_text(f"#!{sys.executable}\n" + (
            "import sys\n"
            "from urllib.parse import unquote\n"
            "frame = open(unquote(sys.argv[-1][len('file://'):])).read()\n"
            "if '/two/' in frame: sys.exit('cannot render two')\n"
            "out = next(a for a in sys.argv if a.startswith('--screenshot='))[len('--screenshot='):]\n"
            "open(out, 'wb').write(b'png')\n"))
        self.chrome.chmod(0o755)
        self.shots = self.root / "shots"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, str(self.manifest), "--shots", str(self.shots), "--chrome", str(self.chrome), *args],
                              capture_output=True, text=True)

    def test_print_shots_takes_the_entry_then_the_pages_it_links_to_at_each_viewport(self):
        result = self.run_cli("--print-shots", "--viewports", "1280x900, 390x844", "--inner-pages", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        shots = [line.split() for line in result.stdout.splitlines() if line.startswith("  shot ")]
        self.assertEqual([s[2:4] for s in shots], [["one/index.html", "1280x900"], ["one/index.html", "390x844"],
                                                   ["one/z.html", "1280x900"], ["one/z.html", "390x844"],
                                                   ["one/a/first.html", "1280x900"], ["one/a/first.html", "390x844"],
                                                   ["two/index.html", "1280x900"], ["two/index.html", "390x844"]])
        pngs = [s[4] for s in shots]
        self.assertEqual(len(set(pngs)), len(pngs))
        self.assertFalse(self.shots.exists())
        one = self.run_cli("--print-shots").stdout
        self.assertIn("one/z.html", one)
        self.assertNotIn("first.html", one)
        self.assertNotIn("one/z.html", self.run_cli("--print-shots", "--inner-pages", "0").stdout)

    def test_print_shots_skips_the_gallery_and_needs_no_chrome(self):
        (self.root / "entry.html").write_text("<html><body></body></html>")
        (self.root / "inner.html").write_text("<html><body></body></html>")
        self.manifest.write_text(json.dumps({"prototypes": [{"id": "flat", "title": "flat", "entry": "entry.html", "dir": "."}]}))
        result = subprocess.run([sys.executable, SCRIPT, str(self.manifest), "--shots", str(self.shots), "--print-shots",
                                 "--chrome", "no-such-chrome-xyz", "--inner-pages", "1"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        listed = [line.split()[2] for line in result.stdout.splitlines() if line.startswith("  shot ")]
        self.assertEqual(listed[0], "entry.html")
        self.assertNotIn("index.html", listed)

    def test_shots_report_each_png_and_fail_when_chrome_writes_none(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn("2 of 3 screenshots", result.stdout)
        self.assertIn("screenshot failed: two/index.html at 1280x900: cannot render", result.stderr)
        self.assertEqual(sorted(p.name for p in self.shots.iterdir()), ["p-1-a-0-1280x900.png", "p-1-a-1-1280x900.png"])

    def test_bad_shot_options_fail_before_writing(self):
        for args, message in [(("--viewports", "1280"), "bad viewport"), (("--chrome", "no-such-chrome-xyz"), "not found")]:
            result = subprocess.run([sys.executable, SCRIPT, str(self.manifest), "--shots", str(self.shots), *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, args)
            self.assertIn(message, result.stderr)
        result = subprocess.run([sys.executable, SCRIPT, str(self.manifest), "--print-shots"], capture_output=True, text=True)
        self.assertIn("needs --shots", result.stderr)
        self.assertFalse((self.root / "index.html").exists())

    @unittest.skipUnless(_has_chrome(), "no headless Chrome")
    def test_real_chrome_lays_out_at_the_requested_viewport(self):
        # Red at the 390px viewport, blue otherwise; bare --window-size keeps the layout 500px wide and shows blue.
        (self.root / "one" / "index.html").write_text(
            "<html><head><style>html{background:#00f}@media (max-width:450px){html{background:#f00}}</style></head><body></body></html>")
        self.manifest.write_text(json.dumps({"prototypes": [{"id": "one", "title": "one", "entry": "one/index.html"}]}))
        result = subprocess.run([sys.executable, SCRIPT, str(self.manifest), "--no-stamp", "--shots", str(self.shots),
                                 "--viewports", "390x844,1280x900"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(first_pixel(self.shots / "p-1-a-0-390x844.png"), (255, 0, 0))
        self.assertEqual(first_pixel(self.shots / "p-1-a-0-1280x900.png"), (0, 0, 255))


def first_pixel(png):
    """RGB of the top-left pixel. Every PNG filter leaves the first pixel of the first row unchanged."""
    data, pos, idat = png.read_bytes(), 8, b""
    while pos < len(data):
        size, kind = int.from_bytes(data[pos:pos + 4], "big"), data[pos + 4:pos + 8]
        if kind == b"IDAT":
            idat += data[pos + 8:pos + 8 + size]
        pos += 12 + size
    return tuple(zlib.decompress(idat)[1:4])


if __name__ == "__main__":
    unittest.main()
