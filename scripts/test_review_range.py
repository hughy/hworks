import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "review-range.py")


def show(models):
    lines = ["profile: test"]
    for role in ("coder", "explorer", "reviewer", "synthesizer"):
        lines.append(f"{role}  {models.get(role, '(session model)')}")
    for slot in ("review2", "exhaustive"):
        lines.append(f"{slot}  {models.get(slot, '(session model)')} (slot)")
    return "\n".join(lines)


class Fixture(unittest.TestCase):
    """A copy of the script beside a stub models.sh, and a repo: main has one commit, work has c1..c4."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "root")
        os.makedirs(os.path.join(self.root, "scripts"))
        shutil.copy(SCRIPT, os.path.join(self.root, "scripts", "review-range.py"))
        stub = os.path.join(self.root, "scripts", "models.sh")
        with open(stub, "w") as f:
            f.write('#!/usr/bin/env bash\nprintf "%s\\n" "$MODELS_SHOW"\n')
        os.chmod(stub, 0o755)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        self.task = os.path.join(self.tmp, "task")
        self.git("init", "-q", "-b", "main")
        self.commit("m0")
        self.main = self.rev("HEAD")
        self.git("checkout", "-q", "-b", "work")
        self.c = [None] + [self.commit(f"c{i}") for i in range(1, 5)]

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def git(self, *a):
        return subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                              capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, msg):
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.rev("HEAD")

    def rev(self, ref):
        return self.git("rev-parse", ref)

    def run_script(self, *args, models=None, env=None):
        e = dict(os.environ, MODELS_SHOW=show(models or {}))
        e.pop("PI_PROVIDER", None)
        e.pop("PI_MODEL", None)
        e.update(env or {})
        return subprocess.run([sys.executable, os.path.join(self.root, "scripts", "review-range.py"), *args,
                               "--cwd", self.repo], capture_output=True, text=True, env=e)

    def record(self, base, head, source="review-loop"):
        r = self.run_script("record", self.task, base, head, source)
        self.assertEqual(r.returncode, 0, r.stderr)

    def base(self):
        r = self.run_script("base", self.task, "main")
        return r.stdout.strip(), r.returncode


class Base(Fixture):
    def test_no_ledger_reviews_from_the_merge_base(self):
        self.assertEqual(self.base(), (self.main, 0))

    def test_review_loop_range_then_incremental(self):
        self.record(self.main, self.c[2])
        self.assertEqual(self.base(), (self.c[2], 0))
        self.record(self.c[2], self.c[4], "pre-push")
        self.assertEqual(self.base(), (self.c[4], 3))

    def test_range_starting_later_than_the_merge_base_does_not_count(self):
        self.record(self.c[1], self.c[3])
        self.assertEqual(self.base(), (self.main, 0))

    def test_older_base_covers_and_furthest_head_wins(self):
        self.record(self.main, self.c[1])
        self.record(self.main, self.c[3])
        self.record(self.c[1], self.c[2])
        self.assertEqual(self.base(), (self.c[3], 0))

    def test_rebase_drops_recorded_ranges(self):
        self.record(self.main, self.c[4])
        self.git("checkout", "-q", "main")
        new_main = self.commit("m1")
        self.git("checkout", "-q", "work")
        self.git("-c", "core.editor=true", "rebase", "-q", "main")
        self.assertEqual(self.base(), (new_main, 0))

    def test_head_not_on_branch_is_ignored(self):
        self.git("checkout", "-q", "-b", "side", self.c[2])
        side = self.commit("s1")
        self.git("checkout", "-q", "work")
        self.record(self.main, side)
        self.assertEqual(self.base(), (self.main, 0))

    def test_record_rejects_bad_ranges(self):
        r = self.run_script("record", self.task, self.c[3], self.c[1], "x")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not an ancestor", r.stderr)
        r = self.run_script("record", self.task, "nope", self.c[1], "x")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(self.task, "reviewed.tsv")))

    def test_record_stores_full_shas(self):
        self.record("main", "HEAD")
        with open(os.path.join(self.task, "reviewed.tsv")) as f:
            self.assertEqual(f.read(), f"{self.main}\t{self.c[4]}\treview-loop\n")


class Args(Fixture):
    def args(self, effort, **kw):
        r = self.run_script("args", self.task, "main", effort, "Add retries to the client.", **kw)
        return r

    def test_standard_runs_one_reviewer_over_the_unreviewed_range(self):
        self.record(self.main, self.c[2])
        r = self.args("standard")
        self.assertEqual(r.returncode, 0, r.stderr)
        a = json.loads(r.stdout)
        [t] = a["targets"]
        self.assertEqual((t["key"], t["base"], t["cwd"]), ("branch", self.c[2], os.path.realpath(self.repo)))
        self.assertIn("Add retries to the client.", t["task"])
        self.assertIn(f"Review only the commits after {self.c[2][:12]}", t["task"])
        self.assertEqual(a["reviewers"], [{"agent": "reviewer", "label": "reviewer"}])
        self.assertIn(os.path.join(self.root, "skills", "interrogate", "references", "rubric.md"), a["task"])
        self.assertEqual((a["label"], a["taskDir"]), ("pre-push", os.path.abspath(self.task)))

    def test_whole_branch_when_nothing_recorded(self):
        t = json.loads(self.args("standard").stdout)["targets"][0]
        self.assertEqual(t["base"], self.main)
        self.assertIn("Review the whole branch.", t["task"])

    def test_exhaustive_adds_review2_and_warns_on_one_model(self):
        a = json.loads(self.args("exhaustive", models={"reviewer": "p/a", "review2": "q/b"}).stdout)
        self.assertEqual(a["reviewers"][1], {"agent": "reviewer", "label": "review2", "model": "q/b"})
        r = self.args("exhaustive", models={"reviewer": "p/a", "review2": "p/a:high"})
        self.assertIn("both reviews run on one model", r.stderr)
        r = self.args("exhaustive", models={"reviewer": "p/a"})
        self.assertNotIn("model", json.loads(r.stdout)["reviewers"][1])
        self.assertIn("review2 slot is the session model", r.stderr)
        r = self.args("exhaustive", models={"reviewer": "p/a"}, env={"PI_PROVIDER": "s", "PI_MODEL": "m"})
        self.assertEqual(json.loads(r.stdout)["reviewers"][1]["model"], "s/m")

    def test_nothing_to_review(self):
        r = self.args("quick")
        self.assertEqual((r.returncode, r.stdout), (3, ""))
        self.assertIn("quick effort runs no review", r.stderr)
        self.record(self.main, self.c[4])
        r = self.args("standard")
        self.assertEqual((r.returncode, r.stdout), (3, ""))
        self.assertIn("already passed review", r.stderr)

    def test_bad_input(self):
        self.assertEqual(self.args("huge").returncode, 2)
        self.assertEqual(self.run_script("args", self.task, "main", "standard", " ").returncode, 2)
        self.assertEqual(self.run_script("base", self.task, "no-such-trunk").returncode, 2)
        self.assertEqual(self.run_script("frob").returncode, 2)


if __name__ == "__main__":
    unittest.main()
