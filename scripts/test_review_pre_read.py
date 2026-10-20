import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "review-pre-read.py")


class PreRead(unittest.TestCase):
    """A repo whose main has lib/util.py (parse_thing, old_helper), app/main.py calling both, and
    tests/test_util.py importing util; work changes them per test."""

    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.git("init", "-q", "-b", "main")
        self.write("lib/util.py", "def parse_thing(x):\n    return x\n\n\ndef old_helper(y):\n    return y\n")
        self.write("app/main.py", "from util import parse_thing, old_helper\n\nparse_thing(old_helper(1))\n")
        self.write("tests/test_util.py", "import util\n")
        self.commit("m0")
        self.main = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "-b", "work")

    def tearDown(self):
        shutil.rmtree(self.repo)

    def git(self, *a):
        r = subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                           capture_output=True, text=True)
        if r.returncode:
            raise AssertionError(f"git {a}: {r.stderr}")
        return r.stdout.strip()

    def write(self, path, text):
        full = os.path.join(self.repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def run_script(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args, "--cwd", self.repo], capture_output=True, text=True)

    def report(self):
        r = self.run_script("main", "HEAD", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def names(self, report):
        return {n["name"]: n for n in report["removed_names"]["names"]}

    def test_removed_function_lists_its_surviving_caller(self):
        self.write("lib/util.py", "def parse_thing(x):\n    return x\n")
        self.commit("drop old_helper")
        rep = self.report()
        hit = self.names(rep)["old_helper"]
        self.assertEqual(hit["count"], 2)
        self.assertEqual(hit["hits"][0], "app/main.py:1:from util import parse_thing, old_helper")
        text = self.run_script("main", "HEAD").stdout
        self.assertIn("old_helper: 2 surviving references\n  app/main.py:1:", text)
        self.assertIn("Heuristic", text)

    def test_renamed_symbol_lists_the_old_names_survivors_and_not_kept_names(self):
        self.write("lib/util.py", "def parse_item(x):\n    return x\n\n\ndef old_helper(y):\n    return y\n")
        self.commit("rename parse_thing")
        rep = self.report()
        names = self.names(rep)
        self.assertEqual(names["parse_thing"]["count"], 2)
        self.assertEqual(names["parse_thing"]["hits"][1], "app/main.py:3:parse_thing(old_helper(1))")
        self.assertNotIn("parse_item", names)
        self.assertNotIn("return", names)

    def test_name_on_removed_and_added_lines_is_not_listed(self):
        self.write("lib/util.py", "def parse_thing(x, z=0):\n    return x\n\n\ndef old_helper(y):\n    return y\n")
        self.commit("add a param")
        rep = self.report()
        self.assertEqual(rep["removed_names"]["names"], [])
        self.assertEqual(rep["removed_names"]["removed_cleanly"], [])

    def test_name_with_no_survivors_is_removed_cleanly(self):
        self.write("app/main.py", "from util import parse_thing\n\nparse_thing(1)\n")
        self.write("lib/util.py", "def parse_thing(x):\n    return x\n")
        self.commit("drop old_helper everywhere")
        rep = self.report()
        self.assertEqual(rep["removed_names"]["removed_cleanly"], ["old_helper"])
        self.assertIn("removed cleanly: old_helper", self.run_script("main", "HEAD").stdout)

    def test_prose_files_contribute_only_backticked_names(self):
        self.write("docs/guide.md", "Call `old_helper` before parse_thing. Run the checks, then fix the rest.\n")
        self.commit("doc")
        self.write("docs/guide.md", "Call parse_thing.\n")
        self.commit("shorten doc")
        r = self.run_script(self.git("rev-parse", "HEAD~1"), "HEAD", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rn = json.loads(r.stdout)["removed_names"]
        self.assertEqual([n["name"] for n in rn["names"]], ["old_helper"])
        self.assertEqual(rn["removed_cleanly"], [])

    def test_prose_filter_applies_to_git_quoted_paths(self):
        words = " ".join(f"word{i}" for i in range(60))
        self.write("docs/caf\u00e9.md", f"{words} and `old_helper`.\n")
        self.commit("doc with a quoted path")
        self.write("docs/caf\u00e9.md", "Short.\n")
        self.commit("shorten it")
        r = self.run_script(self.git("rev-parse", "HEAD~1"), "HEAD", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rn = json.loads(r.stdout)["removed_names"]
        self.assertEqual(([n["name"] for n in rn["names"]], rn["total"]), (["old_helper"], 1))

    def test_related_tests_by_stem_and_changed_tests(self):
        self.write("lib/util.py", "def parse_thing(x):\n    return x + 1\n")
        self.write("tests/test_util.py", "import util\nutil.parse_thing(1)\n")
        self.commit("change util and its test")
        rep = self.report()
        self.assertEqual(rep["related_tests"], {"by_file": {"lib/util.py": ["tests/test_util.py"]},
                                                "changed_tests": ["tests/test_util.py"]})
        self.assertEqual(rep["changed_files"], [{"status": "M", "path": "lib/util.py"},
                                                {"status": "M", "path": "tests/test_util.py"}])

    def test_rename_keeps_old_and_new_paths(self):
        self.git("mv", "lib/util.py", "lib/helpers.py")
        self.commit("rename util")
        rep = self.report()
        self.assertEqual(rep["changed_files"], [{"status": "R100", "old_path": "lib/util.py", "path": "lib/helpers.py"}])
        self.assertIn("## Changed files\n\nR100\tlib/util.py\tlib/helpers.py\n", self.run_script("main", "HEAD").stdout)

    def test_diff_text_is_verbatim_with_crlf_and_unicode_separators(self):
        with open(os.path.join(self.repo, "crlf.txt"), "wb") as f:
            f.write("one\r\ntwo\u2028three\r\n".encode())
        self.commit("crlf")
        r = subprocess.run(["git", "-C", self.repo, "diff", "--no-color", "main...HEAD", "--"], capture_output=True)
        rep = self.report()
        self.assertEqual(rep["diff"]["text"].encode(), r.stdout)
        self.assertIn("+one\r\n+two\u2028three\r\n", rep["diff"]["text"])
        self.assertEqual(rep["diff"]["lines"], 8)

    def test_bad_ref_exits_2_with_no_report(self):
        r = self.run_script("no-such-ref", "HEAD")
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("no-such-ref", r.stderr)

    def test_json_and_text_carry_the_same_sections(self):
        self.write("lib/util.py", "def parse_thing(x):\n    return x\n")
        self.commit("drop old_helper")
        rep = self.report()
        self.assertEqual(list(rep), ["changed_files", "removed_names", "related_tests", "diff"])
        self.assertIn("-def old_helper(y):", rep["diff"]["text"])
        text = self.run_script("main", "HEAD").stdout
        heads = [line for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(heads, ["## Changed files", "## Removed or renamed names", "## Related tests", "## Diff"])

    def test_out_writes_the_file(self):
        out = os.path.join(self.repo, "..", os.path.basename(self.repo) + "-pre-read.md")
        self.addCleanup(lambda: os.path.exists(out) and os.remove(out))
        r = self.run_script("main", "HEAD", "--out", out)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        with open(out) as f:
            self.assertTrue(f.read().startswith("## Changed files\n"))

    def test_long_diff_is_cut_with_a_message(self):
        self.write("big.txt", "".join(f"line {i}\n" for i in range(5000)))
        self.commit("big")
        text = self.run_script("main", "HEAD").stdout
        self.assertIn("lines cut; see the rest: git diff main...HEAD | tail -n +4001", text)
        self.assertNotIn("line 4999", text)
        self.assertEqual(self.report()["diff"]["cut"], 5000 + 6 - 4000)


if __name__ == "__main__":
    unittest.main()
