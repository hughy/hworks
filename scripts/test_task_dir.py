import hashlib
import os
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "task-dir.sh")


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True)


def read_task(d):
    with open(os.path.join(d, ".task")) as f:
        return dict(line.rstrip("\n").split("=", 1) for line in f)


class TaskDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.realpath(self.tmp.name)
        self.state = os.path.join(self.base, "state")
        self.repo = os.path.join(self.base, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "remote", "add", "origin", "git@github.com:Owner/Proj.git")
        self.env = {k: v for k, v in os.environ.items() if k not in ("HWORKS_TASKS_DIR", "XDG_STATE_HOME")}
        self.env["XDG_STATE_HOME"] = self.state

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args, env=None, cwd=None):
        r = subprocess.run(
            ["bash", SCRIPT, *args], env=env or self.env, cwd=cwd, capture_output=True, text=True, check=True
        )
        return r.stdout.strip()

    def on_branch(self, name, slug="t"):
        git(self.repo, "checkout", "-q", "-B", name)
        return self.run_script(slug, self.repo)

    def test_xdg_state_home_root(self):
        out = self.on_branch("main")
        self.assertEqual(out, os.path.join(self.state, "agent-tasks", "github.com--owner--proj", "main", "t"))
        self.assertTrue(os.path.isdir(out))

    def test_home_default_root(self):
        env = dict(self.env, HOME=self.base)
        del env["XDG_STATE_HOME"]
        out = self.run_script("t", self.repo, env=env)
        self.assertEqual(out, os.path.join(self.base, ".local/state/agent-tasks/github.com--owner--proj/main/t"))

    def test_hworks_tasks_dir_wins(self):
        root = os.path.join(self.base, "custom")
        out = self.run_script("t", self.repo, env=dict(self.env, HWORKS_TASKS_DIR=root))
        self.assertEqual(out, os.path.join(root, "github.com--owner--proj", "main", "t"))

    def test_outside_repo_misc(self):
        plain = os.path.join(self.base, "plain")
        os.makedirs(plain)
        out = self.run_script("t", plain)
        self.assertEqual(out, os.path.join(self.state, "agent-tasks", "_misc", "t"))
        meta = read_task(out)
        self.assertEqual((meta["repo"], meta["branch"], meta["cwd"]), ("_misc", "", plain))

    def test_lossless_branch_unchanged(self):
        out = self.on_branch("feat/ui-shots")
        self.assertEqual(os.path.basename(os.path.dirname(out)), "feat--ui-shots")

    def test_slash_and_double_dash_distinct(self):
        a = os.path.basename(os.path.dirname(self.on_branch("feat/a")))
        b = os.path.basename(os.path.dirname(self.on_branch("feat--a")))
        self.assertEqual(a, "feat--a")
        self.assertRegex(b, r"^feat--a-[0-9a-f]{8}$")
        self.assertNotEqual(a, b)

    def test_dash_slash_unchanged(self):
        a = os.path.basename(os.path.dirname(self.on_branch("a/-b")))
        b = os.path.basename(os.path.dirname(self.on_branch("a-/b")))
        self.assertEqual((a, b), ("a---b", "a---b"))

    def test_case_distinct(self):
        lower = os.path.basename(os.path.dirname(self.on_branch("feat")))
        upper = os.path.basename(os.path.dirname(self.on_branch("Feat")))
        self.assertEqual(lower, "feat")
        self.assertRegex(upper, r"^feat-[0-9a-f]{8}$")

    def test_suffix_deterministic(self):
        first = self.on_branch("Feat")
        expected = hashlib.sha1(b"Feat").hexdigest()[:8]
        self.assertEqual(os.path.basename(os.path.dirname(first)), "feat-" + expected)
        self.assertEqual(self.run_script("t", self.repo), first)

    def test_suffix_independent_of_caller_repo(self):
        first = self.on_branch("Feat")
        caller = os.path.join(self.base, "sha256")
        os.makedirs(caller)
        git(caller, "init", "-q", "--object-format=sha256")
        self.assertEqual(self.run_script("t", self.repo, cwd=caller), first)

    def test_concurrent_creator_marker_kept(self):
        out = os.path.join(self.state, "agent-tasks", "github.com--owner--proj", "main", "t")
        shims = os.path.join(self.base, "bin")
        os.makedirs(shims)
        real = subprocess.run(["sh", "-c", "command -v mkdir"], capture_output=True, text=True).stdout.strip()
        shim = os.path.join(shims, "mkdir")
        with open(shim, "w") as f:
            f.write(
                "#!/bin/sh\n"
                'for a; do last=$a; done\n'
                'if [ "$last" = "$RACE_DIR" ] && [ ! -e "$last" ]; then\n'
                f'  {real} -p "$last" && echo sentinel > "$last/.task"\n'
                "fi\n"
                f'exec {real} "$@"\n'
            )
        os.chmod(shim, 0o755)
        env = dict(self.env, PATH=shims + os.pathsep + self.env["PATH"], RACE_DIR=out)
        self.assertEqual(self.run_script("t", self.repo, env=env), out)
        with open(os.path.join(out, ".task")) as f:
            self.assertEqual(f.read(), "sentinel\n")

    def test_marker_written_once(self):
        out = self.on_branch("feat/x")
        meta = read_task(out)
        self.assertEqual(sorted(meta), ["branch", "created", "cwd", "repo", "slug"])
        self.assertRegex(meta["created"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(meta["repo"], "github.com--owner--proj")
        self.assertEqual(meta["branch"], "feat/x")
        self.assertEqual(meta["slug"], "t")
        self.assertEqual(meta["cwd"], self.repo)
        marker = os.path.join(out, ".task")
        with open(marker, "w") as f:
            f.write("sentinel\n")
        self.run_script("t", self.repo)
        with open(marker) as f:
            self.assertEqual(f.read(), "sentinel\n")

    def test_no_marker_in_existing_dir(self):
        pre = os.path.join(self.state, "agent-tasks", "github.com--owner--proj", "main", "t")
        os.makedirs(pre)
        self.assertEqual(self.run_script("t", self.repo), pre)
        self.assertFalse(os.path.exists(os.path.join(pre, ".task")))

    def test_file_blocking_leaf_fails(self):
        blocked = os.path.join(self.state, "agent-tasks", "github.com--owner--proj", "main", "t")
        os.makedirs(os.path.dirname(blocked))
        open(blocked, "w").close()
        r = subprocess.run(["bash", SCRIPT, "t", self.repo], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")
        self.assertIn("mkdir", r.stderr)


if __name__ == "__main__":
    unittest.main()
