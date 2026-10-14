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
    """A copy of the script beside a stub models.sh, and a repo: main has m0, work has c1..c4,
    each commit editing its own file."""

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
        self.commit("m0", "shared.txt", "a\nb\nc\n")
        self.main = self.rev("HEAD")
        self.git("checkout", "-q", "-b", "work")
        self.c = [None] + [self.commit(f"c{i}", f"f{i}.txt", f"{i}\n") for i in range(1, 5)]

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def git(self, *a, check=True):
        r = subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                           capture_output=True, text=True, env=dict(os.environ, GIT_EDITOR="true"))
        if check and r.returncode:
            raise AssertionError(f"git {a}: {r.stderr}")
        return r.stdout.strip()

    def commit(self, msg, path=None, text=None):
        if path:
            with open(os.path.join(self.repo, path), "w") as f:
                f.write(text)
            self.git("add", path)
            self.git("commit", "-q", "-m", msg)
        else:
            self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.rev("HEAD")

    def rev(self, ref):
        return self.git("rev-parse", ref)

    def on(self, branch, *commits):
        """Check out branch, add commits as (msg, path, text), return to work."""
        self.git("checkout", "-q", branch)
        out = [self.commit(*c) for c in commits]
        self.git("checkout", "-q", "work")
        return out

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

    def base(self, trunk="main"):
        r = self.run_script("base", self.task, trunk)
        self.assertIn(r.returncode, (0, 3), r.stderr)
        return r.stdout.strip(), r.returncode


class Base(Fixture):
    def test_no_ledger_reviews_from_the_merge_base(self):
        self.assertEqual(self.base(), (self.main, 0))

    def test_review_loop_range_then_incremental(self):
        self.record(self.main, self.c[2])
        self.assertEqual(self.base(), (self.c[2], 0))
        self.record(self.c[2], self.c[4], "pre-push")
        self.assertEqual(self.base(), (self.c[4], 3))

    def test_first_unreviewed_commit_stops_the_walk(self):
        self.record(self.c[1], self.c[3])
        self.assertEqual(self.base(), (self.main, 0))

    def test_rebase_onto_moved_trunk_keeps_coverage(self):
        self.record(self.main, self.c[4])
        self.on("main", ("m1", "other.txt", "x\n"))
        self.git("rebase", "-q", "main")
        self.assertEqual(self.base(), (self.rev("HEAD"), 3))

    def test_conflict_that_changes_a_commit_reviews_from_it(self):
        self.git("checkout", "-q", "-b", "edit", self.c[2])
        self.commit("c3 edits shared", "shared.txt", "a\nB\nc\n")
        c4 = self.commit("c4", "g.txt", "g\n")
        self.git("branch", "-f", "work", c4)
        self.git("checkout", "-q", "work")
        self.record(self.main, c4)
        self.on("main", ("m1 edits shared", "shared.txt", "a\nb2\nc\n"))
        self.git("rebase", "-q", "main", check=False)
        with open(os.path.join(self.repo, "shared.txt"), "w") as f:
            f.write("a\nB2\nc\n")
        self.git("add", "shared.txt")
        self.git("rebase", "--continue")
        new_c2 = self.rev("HEAD~2")
        self.assertEqual(self.git("log", "-1", "--format=%s", "HEAD~1"), "c3 edits shared")
        self.assertNotEqual(new_c2, self.c[2])
        self.assertEqual(self.base(), (new_c2, 0))

    def test_squash_merged_lower_pr_then_stack_rebase(self):
        lower_tip = self.c[2]
        self.git("branch", "lower", lower_tip)
        self.record(lower_tip, self.c[4], "pre-push")
        self.assertEqual(self.base("lower"), (self.c[4], 3))
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--squash", "lower")
        self.git("commit", "-q", "-m", "lower (squash)")
        self.git("checkout", "-q", "work")
        self.git("rebase", "-q", "--onto", "main", "lower", "work")
        self.assertEqual(self.base(), (self.rev("HEAD"), 3))

    def test_clean_trunk_merge_is_covered(self):
        self.record(self.main, self.c[4])
        self.on("main", ("m1", "other.txt", "x\n"))
        self.git("merge", "-q", "--no-ff", "--no-edit", "main")
        self.assertEqual(self.base(), (self.rev("HEAD"), 3))

    def test_merge_with_conflict_resolution_is_reviewed(self):
        self.commit("c5 edits shared", "shared.txt", "a\nW\nc\n")
        self.record(self.main, "HEAD")
        before = self.rev("HEAD")
        self.on("main", ("m1 edits shared", "shared.txt", "a\nM\nc\n"))
        self.git("merge", "-q", "--no-edit", "main", check=False)
        with open(os.path.join(self.repo, "shared.txt"), "w") as f:
            f.write("a\nWM\nc\n")
        self.git("add", "shared.txt")
        self.git("commit", "-q", "--no-edit")
        self.assertEqual(self.base(), (before, 0))

    def test_merge_of_a_non_trunk_branch_is_reviewed(self):
        self.record(self.main, self.c[4])
        self.git("checkout", "-q", "-b", "side", self.c[2])
        self.commit("s1", "side.txt", "s\n")
        self.git("checkout", "-q", "work")
        self.git("merge", "-q", "--no-ff", "--no-edit", "side")
        self.assertEqual(self.base(), (self.c[4], 0))

    def test_empty_commit_needs_no_review(self):
        self.record(self.main, self.c[4])
        self.commit("empty")
        self.assertEqual(self.base(), (self.rev("HEAD"), 3))

    def test_reviewed_commit_elsewhere_does_not_cover(self):
        self.git("checkout", "-q", "-b", "side", self.c[2])
        side = self.commit("s1", "side.txt", "s\n")
        self.git("checkout", "-q", "work")
        self.record(self.c[2], side)
        self.assertEqual(self.base(), (self.main, 0))

    def test_record_rejects_bad_ranges(self):
        r = self.run_script("record", self.task, self.c[3], self.c[1], "x")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not an ancestor", r.stderr)
        r = self.run_script("record", self.task, "nope", self.c[1], "x")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(self.task, "reviewed.tsv")))

    def test_record_writes_one_line_per_commit(self):
        self.commit("empty")
        self.record("main", "HEAD")
        with open(os.path.join(self.task, "reviewed.tsv")) as f:
            rows = [line.rstrip("\n").split("\t") for line in f]
        self.assertEqual([r[1] for r in rows], self.c[1:] + [self.rev("HEAD")])
        self.assertTrue(all(len(r[0]) == 40 for r in rows[:4]))
        self.assertEqual(rows[4][0], "-")
        self.assertEqual({r[2] for r in rows}, {"review-loop"})


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
