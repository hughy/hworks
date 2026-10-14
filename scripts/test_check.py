import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest

CHECK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check.sh")


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="check-test-")
        os.mkdir(os.path.join(self.root, "scripts"))
        self.addCleanup(shutil.rmtree, self.root)

    def module(self, name, body):
        with open(os.path.join(self.root, "scripts", name + ".py"), "w") as f:
            f.write("import os, time, unittest\n\n\nclass T(unittest.TestCase):\n    def test_it(self):\n")
            f.write(textwrap.indent(textwrap.dedent(body), "        "))

    def run_check(self, jobs):
        env = dict(os.environ, CHECK_ROOT=self.root, CHECK_JOBS=str(jobs))
        return subprocess.run(["bash", CHECK], env=env, capture_output=True, text=True, timeout=60)

    def test_failure_exits_nonzero_and_prints_failed_output(self):
        self.module("test_good", "print('good-output')\n")
        self.module("test_bad", "self.fail('bad-marker')\n")
        p = self.run_check(4)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"ok +py:test_good")
        self.assertRegex(p.stdout, r"FAIL +py:test_bad")
        self.assertIn("===== py:test_bad:", p.stdout)
        self.assertIn("bad-marker", p.stdout)
        self.assertNotIn("good-output", p.stdout)
        self.assertIn("1 of 2 parts failed", p.stdout)

    def test_success_exits_zero(self):
        self.module("test_a", "pass\n")
        self.module("test_b", "pass\n")
        p = self.run_check(4)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("all 2 parts passed", p.stdout)

    def test_modules_run_concurrently(self):
        a, b = os.path.join(self.root, "a"), os.path.join(self.root, "b")
        for me, other in ((a, b), (b, a)):
            self.module("test_" + os.path.basename(me), f"""\
                open({me!r}, 'w').close()
                deadline = time.time() + 20
                while not os.path.exists({other!r}):
                    self.assertLess(time.time(), deadline, 'other module never started')
                    time.sleep(0.05)
                """)
        p = self.run_check(2)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_job_cap_bounds_concurrency(self):
        live = os.path.join(self.root, "live")
        os.mkdir(live)
        for name in ("a", "b", "c"):
            self.module("test_" + name, f"""\
                mine = os.path.join({live!r}, {name!r})
                open(mine, 'w').close()
                time.sleep(0.5)
                self.assertEqual(os.listdir({live!r}), [{name!r}])
                os.remove(mine)
                """)
        p = self.run_check(1)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_empty_root_fails(self):
        p = self.run_check(1)
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main()
