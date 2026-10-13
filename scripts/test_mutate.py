import errno
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "mutate.py")
sys.path.insert(0, HERE)
import mutate  # noqa: E402

BUGGY = "def add(a, b):\n    return a - b\n"
CALC = "def add(a, b):\n    return a + b\n\n\ndef double(x):\n    return x * 2\n"
# add() is tested and double() is not, so a mutant in double() survives.
CHECK = "import calc\n\nassert calc.add(2, 3) == 5, 'add is wrong'\n"
TEST = [sys.executable, "check.py"]


def git(cwd, *args):
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(args), cwd=cwd,
                       capture_output=True, text=True, check=True)
    return p.stdout.strip()


def write(path, data):
    with open(path, "wb") as f:
        f.write(data.encode() if isinstance(data, str) else data)


def read(path):
    with open(path, "rb") as f:
        return f.read()


class MutateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="mutate-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "repo")
        self.scratch_root = os.path.join(self.tmp, "scratch")
        os.makedirs(self.repo)
        os.makedirs(self.scratch_root)
        git(self.repo, "init", "-q", "-b", "main")
        write(os.path.join(self.repo, "calc.py"), BUGGY)
        write(os.path.join(self.repo, "check.py"), CHECK)
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "buggy")
        write(os.path.join(self.repo, "calc.py"), CALC)
        git(self.repo, "commit", "-q", "-am", "fix add")
        self.calc = os.path.join(self.repo, "calc.py")
        self.env = dict(os.environ, TMPDIR=self.scratch_root)
        self.env.pop("PYTHONDONTWRITEBYTECODE", None)
        self.env.pop("PYTHONPYCACHEPREFIX", None)

    def mutate(self, spec, *flags, code=None, cwd=None):
        p = subprocess.run([sys.executable, SCRIPT] + list(flags) + ["-"], input=json.dumps(spec), text=True,
                           capture_output=True, cwd=cwd or self.repo, env=self.env, timeout=120)
        if code is not None:
            self.assertEqual(p.returncode, code, "stdout: %s\nstderr: %s" % (p.stdout, p.stderr))
        return p

    def results(self, spec, *flags, code):
        return json.loads(self.mutate(spec, "--json", *flags, code=code).stdout)

    def one(self, mutant, *flags, code):
        [r] = self.results({"test": TEST, "mutants": [mutant]}, *flags, code=code)
        return r

    def test_killed_mutant_restores_file(self):
        before = read(self.calc)
        r = self.one({"name": "minus", "file": "calc.py", "old": "a + b", "new": "a - b"}, code=0)
        self.assertEqual((r["verdict"], r["mode"], r["exit"]), ("killed", "in-place", 1))
        self.assertEqual(read(self.calc), before)

    def test_survived_mutant(self):
        before = read(self.calc)
        r = self.one({"name": "triple", "file": "calc.py", "old": "x * 2", "new": "x * 3"}, code=1)
        self.assertEqual((r["verdict"], r["exit"]), ("survived", 0))
        self.assertEqual(read(self.calc), before)

    def test_old_missing_is_invalid(self):
        r = self.one({"name": "nope", "file": "calc.py", "old": "a * b", "new": "a - b"}, code=2)
        self.assertEqual(r["verdict"], "invalid")
        self.assertIn("old not found", r["reason"])
        self.assertIsNone(r["exit"])

    def test_old_not_unique_is_invalid(self):
        r = self.one({"name": "twice", "file": "calc.py", "old": "return", "new": "yield"}, code=2)
        self.assertEqual(r["verdict"], "invalid")
        self.assertIn("more than once", r["reason"])
        self.assertEqual(read(self.calc), CALC.encode())

    def test_overlapping_occurrences_are_not_unique(self):
        write(self.calc, CALC + "\nPAD = 'aaa'\n")
        git(self.repo, "commit", "-q", "-am", "pad")
        r = self.one({"name": "overlap", "file": "calc.py", "old": "aa", "new": "b"}, code=2)
        self.assertIn("more than once", r["reason"])

    def test_missing_file_is_invalid(self):
        r = self.one({"name": "ghost", "file": "nope.py", "old": "a", "new": "b"}, code=2)
        self.assertIn("no such file", r["reason"])

    def test_noop_swap_is_invalid(self):
        r = self.one({"name": "same", "file": "calc.py", "old": "a + b", "new": "a + b"}, code=2)
        self.assertIn("the same", r["reason"])

    def test_rev_mutant_reverts_the_fix(self):
        r = self.one({"name": "fix-reverted", "file": "calc.py", "rev": "HEAD~1"}, code=0)
        self.assertEqual(r["verdict"], "killed")
        self.assertEqual(read(self.calc), CALC.encode())

    def test_rev_mutant_from_subdirectory_cwd(self):
        sub = os.path.join(self.repo, "pkg")
        os.makedirs(sub)
        write(os.path.join(sub, "calc.py"), BUGGY)
        write(os.path.join(sub, "check.py"), CHECK)
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "pkg buggy")
        write(os.path.join(sub, "calc.py"), CALC)
        git(self.repo, "commit", "-q", "-am", "pkg fix")
        [r] = self.results({"cwd": "pkg", "test": TEST,
                            "mutants": [{"name": "rev", "file": "calc.py", "rev": "HEAD~1"}]}, code=0)
        self.assertEqual(r["verdict"], "killed")
        self.assertEqual(read(os.path.join(sub, "calc.py")), CALC.encode())

    def test_unknown_rev_is_invalid(self):
        r = self.one({"name": "bad-rev", "file": "calc.py", "rev": "no-such-rev"}, code=2)
        self.assertEqual(r["verdict"], "invalid")
        self.assertIn("no-such-rev", r["reason"])

    def test_rev_identical_to_worktree_is_invalid(self):
        r = self.one({"name": "same-rev", "file": "calc.py", "rev": "HEAD"}, code=2)
        self.assertIn("identical", r["reason"])

    def test_restore_is_byte_identical_for_binary_and_crlf_content(self):
        data = b"def add(a, b):\r\n    return a + b\r\n# caf\xc3\xa9 \xe2\x9c\x93\r\n\r\n\r\ndef double(x):\r\n    return x * 2"
        write(self.calc, data)
        os.chmod(self.calc, 0o640)
        git(self.repo, "commit", "-q", "-am", "crlf")
        r = self.one({"name": "minus", "file": "calc.py", "old": "a + b", "new": "a - b"}, code=0)
        self.assertEqual(r["verdict"], "killed")
        self.assertEqual(read(self.calc), data)
        self.assertEqual(os.stat(self.calc).st_mode & 0o777, 0o640)

    def test_mutant_is_applied_while_the_command_runs(self):
        seen = os.path.join(self.tmp, "seen")
        os.utime(self.calc, ns=(1_000_000_000_123, 1_000_000_000_456))
        cmd = [sys.executable, "-c", "import os, shutil, sys; shutil.copy('calc.py', sys.argv[1]); "
               "open(sys.argv[1] + '.mtime', 'w').write(str(os.stat('calc.py').st_mtime_ns)); sys.exit(3)", seen]
        r = self.one({"name": "m", "file": "calc.py", "old": "x * 2", "new": "x * 7", "test": cmd},
                     "--no-baseline", code=0)
        self.assertEqual((r["verdict"], r["exit"]), ("killed", 3))
        self.assertIn(b"x * 7", read(seen))
        self.assertNotEqual(int(read(seen + ".mtime")) // 10**9, 1_000_000_000_456 // 10**9)
        self.assertEqual(read(self.calc), CALC.encode())

    def test_restored_file_is_newer_than_what_the_mutant_built(self):
        # make and similar tools rebuild only when a source is newer than its artifact.
        before, artifact = os.path.join(self.tmp, "before"), os.path.join(self.tmp, "artifact")
        cmd = [sys.executable, "-c", "import os, sys; open(sys.argv[2], 'w').write(str(os.stat('calc.py').st_mtime_ns)); "
               "sys.exit(2)", before, artifact]
        write(before, "built from the original")
        self.one({"name": "m", "file": "calc.py", "old": "x * 2", "new": "x * 7", "test": cmd},
                 "--no-baseline", code=0)
        self.assertGreater(int(read(artifact)), os.stat(before).st_mtime_ns, "the mutant is older than a build")
        self.assertEqual(read(self.calc), CALC.encode())
        self.assertGreater(os.stat(self.calc).st_mtime_ns, os.stat(artifact).st_mtime_ns)

    def test_timestamps_only_move_forward_in_whole_seconds(self):
        seen = os.path.join(self.tmp, "seen")
        cmd = [sys.executable, "-c", "import os, sys; open(sys.argv[1], 'w').write(str(os.stat('calc.py').st_mtime_ns)); "
               "sys.exit(1)", seen]
        mutant = {"name": "m", "file": "calc.py", "old": "a + b", "new": "a - b", "test": cmd}
        future = (time.time_ns() // 10**9 + 30) * 10**9 + 900_000_000
        for orig in (time.time_ns(), future):
            os.utime(self.calc, ns=(orig, orig))
            self.one(mutant, "--no-baseline", code=0)
            mutant_ns, restored_ns = int(read(seen)), os.stat(self.calc).st_mtime_ns
            self.assertGreater(mutant_ns // 10**9, orig // 10**9)
            self.assertGreater(restored_ns // 10**9, mutant_ns // 10**9)
            self.assertEqual(read(self.calc), CALC.encode())

    def check_bytecode_both_ways(self, test, runs):
        # Same-size swap with the original stamped this second, so the mutant, the original, and the
        # restored file would share a .pyc key if any mtime repeated.
        mutant = {"name": "minus", "file": "calc.py", "old": "a + b", "new": "a - b", "test": test}
        os.utime(self.calc)
        subprocess.run(test, cwd=self.repo, env=self.env, check=True)
        for i in range(runs):
            start = time.monotonic()
            r = self.one(mutant, code=0)
            self.assertEqual(r["verdict"], "killed", i)
            p = subprocess.run(test, cwd=self.repo, env=self.env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, "the restored file runs the mutant: %s" % p.stderr)
            self.assertLess(time.monotonic() - start, 30)

    def test_python_dash_e_ignores_the_bytecode_prefix_but_not_the_mtime(self):
        self.check_bytecode_both_ways([sys.executable, "-E", "check.py"], 3)
        self.assertTrue(os.listdir(os.path.join(self.repo, "__pycache__")), "-E wrote no bytecode")

    def test_same_size_mutant_within_one_second_in_normal_python(self):
        self.assertNotIn("PYTHONDONTWRITEBYTECODE", self.env)
        self.check_bytecode_both_ways(TEST, 3)
        self.assertTrue(os.listdir(os.path.join(self.repo, "__pycache__")), "python wrote no bytecode")

    def test_python_bytecode_cache_neither_hides_nor_keeps_the_mutant(self):
        # Same-size swap, so only the mtime and the cache location tell the versions apart.
        mutant = {"name": "minus", "file": "calc.py", "old": "a + b", "new": "a - b"}
        for mtime in (time.time(), 1_000_000_000):
            os.utime(self.calc, (mtime, mtime))
            subprocess.run(TEST, cwd=self.repo, env=self.env, check=True)
            r = self.one(mutant, code=0)
            self.assertEqual(r["verdict"], "killed", mtime)
            p = subprocess.run(TEST, cwd=self.repo, env=self.env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, "the restored file runs the mutant: %s" % p.stderr)

    def test_reused_out_dir_does_not_reuse_an_earlier_runs_bytecode(self):
        out = os.path.join(self.tmp, "out")
        spec = {"test": TEST, "mutants": [{"name": "m", "file": "calc.py", "old": "a + b", "new": "a - b"}]}
        for new, code, verdict in (("a - b", 0, "killed"), ("b + a", 1, "survived"), ("a - b", 0, "killed")):
            spec["mutants"][0]["new"] = new
            self.assertEqual(self.results(spec, "--out", out, code=code)[0]["verdict"], verdict, new)
        prefixes = [d for d in os.listdir(os.path.join(out, "00-m")) if d.startswith("pycache-")]
        self.assertEqual(len(prefixes), 3)

    def test_multiple_files_are_all_mutated_and_restored(self):
        check = os.path.join(self.repo, "check.py")
        before = read(check)
        [r] = self.results({"test": TEST, "mutants": [{"name": "pair", "files": [
            {"file": "calc.py", "old": "a + b", "new": "a - b"},
            {"file": "check.py", "old": "== 5", "new": "== -1"}]}]}, code=1)
        self.assertEqual(r["verdict"], "survived")
        self.assertEqual(r["files"], ["calc.py", "check.py"])
        self.assertEqual(read(check), before)
        self.assertEqual(read(self.calc), CALC.encode())

    def interrupt(self, sig):
        marker = os.path.join(self.tmp, "started")
        # The command spawns a grandchild, as go test does, and records its pid and the file it sees.
        child = ("import os, pathlib, subprocess, sys\n"
                 "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                 "pathlib.Path(sys.argv[1] + '.tmp').write_text('%d\\n' % g.pid + open('calc.py').read())\n"
                 "os.rename(sys.argv[1] + '.tmp', sys.argv[1])\n"
                 "g.wait()\n")
        spec = {"test": [sys.executable, "-c", child, marker],
                "mutants": [{"name": "slow", "file": "calc.py", "old": "a + b", "new": "a - b"}]}
        before = read(self.calc)
        p = subprocess.Popen([sys.executable, SCRIPT, "--no-baseline", "-"], cwd=self.repo, env=self.env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        p.stdin.write(json.dumps(spec))
        p.stdin.close()
        deadline = time.monotonic() + 30
        while not os.path.exists(marker):
            self.assertLess(time.monotonic(), deadline, "the command never started")
            time.sleep(0.05)
        pid_line, seen = read(marker).decode().split("\n", 1)
        self.assertIn("a - b", seen)
        self.assertNotEqual(read(self.calc), before)
        p.send_signal(sig)
        p.wait(30)
        self.assertEqual(p.returncode, 128 + sig, p.stderr.read())
        self.assertEqual(read(self.calc), before)
        grandchild = int(pid_line)
        deadline = time.monotonic() + 10
        while True:
            try:
                os.kill(grandchild, 0)
            except ProcessLookupError:
                break
            self.assertLess(time.monotonic(), deadline, "the test command's child outlived mutate.py")
            time.sleep(0.05)
        p.stdout.close()
        p.stderr.close()

    def test_descendant_ignoring_sigterm_is_stopped_before_restore(self):
        marker, release = os.path.join(self.tmp, "started"), os.path.join(self.tmp, "release")
        grandchild = ("import os, pathlib, signal, sys, time\n"
                      "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                      "pathlib.Path(sys.argv[1] + '.tmp').write_text(str(os.getpid()))\n"
                      "os.rename(sys.argv[1] + '.tmp', sys.argv[1])\n"
                      "while not os.path.exists(sys.argv[2]):\n"
                      "    time.sleep(0.02)\n"
                      "open('calc.py', 'w').write('late child edit')\n")
        child = ("import subprocess, sys\n"
                 "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2], sys.argv[3]]).wait()\n")
        spec = {"test": [sys.executable, "-c", child, grandchild, marker, release],
                "mutants": [{"name": "slow", "file": "calc.py", "old": "a + b", "new": "a - b"}]}
        before = read(self.calc)
        p = subprocess.Popen([sys.executable, SCRIPT, "--no-baseline", "-"], cwd=self.repo, env=self.env,
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        p.stdin.write(json.dumps(spec))
        p.stdin.close()
        deadline = time.monotonic() + 30
        while not os.path.exists(marker):
            self.assertLess(time.monotonic(), deadline, "the command never started")
            time.sleep(0.05)
        pid = int(read(marker))
        self.addCleanup(lambda: subprocess.run(["kill", "-9", str(pid)], capture_output=True))
        p.send_signal(signal.SIGTERM)
        p.wait(30)
        p.stderr.close()
        self.assertEqual(p.returncode, 128 + signal.SIGTERM)
        write(release, "")
        deadline = time.monotonic() + 5
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            if time.monotonic() > deadline:
                break
            time.sleep(0.05)
        time.sleep(0.3)
        self.assertEqual(read(self.calc), before)

    def test_background_process_is_stopped_before_restore(self):
        late = ("import time; time.sleep(0.5); open('calc.py', 'w').write('late child edit')")
        cmd = [sys.executable, "-c", "import subprocess, sys; subprocess.Popen([sys.executable, '-c', sys.argv[1]]); "
               "sys.exit(1)", late]
        r = self.one({"name": "m", "file": "calc.py", "old": "a + b", "new": "a - b", "test": cmd},
                     "--no-baseline", code=0)
        self.assertEqual(r["verdict"], "killed")
        time.sleep(1)
        self.assertEqual(read(self.calc), CALC.encode())

    def test_concurrent_in_place_runs_wait_for_each_other(self):
        marker, release = os.path.join(self.tmp, "started"), os.path.join(self.tmp, "release")
        hold = [sys.executable, "-c", "import os, sys, time\nopen(sys.argv[1], 'w').close()\n"
                "while not os.path.exists(sys.argv[2]):\n    time.sleep(0.02)\nsys.exit(1)", marker, release]
        first = {"test": hold, "mutants": [{"name": "a", "file": "calc.py", "old": "a + b", "new": "a - b"}]}
        second = {"test": TEST, "mutants": [{"name": "b", "file": "calc.py", "old": "a + b", "new": "a * b"}]}
        procs = []
        for spec in (first, second):
            p = subprocess.Popen([sys.executable, SCRIPT, "--no-baseline", "--json", "-"], cwd=self.repo,
                                 env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
            p.stdin.write(json.dumps(spec))
            p.stdin.close()
            procs.append(p)
            deadline = time.monotonic() + 30
            while not os.path.exists(marker):
                self.assertLess(time.monotonic(), deadline, "the first run never started")
                time.sleep(0.05)
        time.sleep(1)
        self.assertIsNone(procs[1].poll(), "the second run did not wait for the first")
        write(release, "")
        for p in procs:
            p.wait(60)
            out, err = p.stdout.read(), p.stderr.read()
            p.stdout.close()
            p.stderr.close()
            self.assertEqual(p.returncode, 0, out + err)
            self.assertEqual(json.loads(out)[0]["verdict"], "killed")
        self.assertIn("waiting for another in-place run", err)
        self.assertEqual(read(self.calc), CALC.encode())
        self.assertEqual(git(self.repo, "status", "--porcelain", "--", "calc.py"), "")

    def test_runs_sharing_an_out_dir_wait_for_each_other(self):
        other = os.path.join(self.tmp, "other")
        git(self.tmp, "clone", "-q", self.repo, other)
        out = os.path.join(self.tmp, "out")
        marker, release = os.path.join(self.tmp, "started"), os.path.join(self.tmp, "release")
        hold = [sys.executable, "-c", "import os, sys, time\nopen(sys.argv[1], 'w').close()\n"
                "while not os.path.exists(sys.argv[2]):\n    time.sleep(0.02)\nsys.exit(1)", marker, release]
        mutant = {"name": "m", "file": "calc.py", "old": "a + b", "new": "a - b"}
        procs = []
        for repo, test in ((self.repo, hold), (other, TEST)):
            p = subprocess.Popen([sys.executable, SCRIPT, "--no-baseline", "--json", "--out", out, "-"],
                                 cwd=repo, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
            p.stdin.write(json.dumps({"test": test, "mutants": [mutant]}))
            p.stdin.close()
            procs.append(p)
            deadline = time.monotonic() + 30
            while not os.path.exists(marker):
                self.assertLess(time.monotonic(), deadline, "the first run never started")
                time.sleep(0.05)
        time.sleep(1)
        waited = procs[1].poll() is None
        write(release, "")
        for p in procs:
            p.wait(60)
            out_text, err = p.stdout.read(), p.stderr.read()
            p.stdout.close()
            p.stderr.close()
            self.assertEqual(p.returncode, 0, out_text + err)
        self.assertTrue(waited, "the second run did not wait for the first")
        self.assertIn("waiting for another run using --out", err)

    def test_sigterm_restores_file_and_stops_command(self):
        self.interrupt(signal.SIGTERM)

    def test_sigint_restores_file_and_stops_command(self):
        self.interrupt(signal.SIGINT)

    def test_dirty_file_is_refused_in_place(self):
        dirty = CALC + "# local edit\n"
        write(self.calc, dirty)
        r = self.one({"name": "minus", "file": "calc.py", "old": "a + b", "new": "a - b"}, code=2)
        self.assertEqual(r["verdict"], "invalid")
        self.assertIn("uncommitted changes", r["reason"])
        self.assertEqual(read(self.calc), dirty.encode())
        r = self.one({"name": "minus", "file": "calc.py", "old": "a + b", "new": "a - b"}, "--allow-dirty", code=0)
        self.assertEqual(r["verdict"], "killed")
        self.assertEqual(read(self.calc), dirty.encode())

    def test_file_hidden_from_git_status_is_refused_in_place(self):
        dirty = CALC + "# local edit\n"
        write(self.calc, dirty)
        for flag in ("--assume-unchanged", "--skip-worktree"):
            git(self.repo, "update-index", flag, "calc.py")
            self.assertEqual(git(self.repo, "status", "--porcelain", "--ignored", "--", "calc.py"), "")
            r = self.one({"name": "minus", "file": "calc.py", "old": "a + b", "new": "a - b"}, code=2)
            self.assertIn("assume-unchanged or skip-worktree", r["reason"], flag)
            self.assertEqual(read(self.calc), dirty.encode())
            git(self.repo, "update-index", flag.replace("--", "--no-", 1), "calc.py")

    def test_symlink_to_dirty_file_is_refused_in_place(self):
        os.symlink("calc.py", os.path.join(self.repo, "link.py"))
        git(self.repo, "add", "link.py")
        git(self.repo, "commit", "-q", "-m", "link")
        dirty = CALC + "# local edit\n"
        write(self.calc, dirty)
        r = self.one({"name": "minus", "file": "link.py", "old": "a + b", "new": "a - b"}, code=2)
        self.assertIn("uncommitted changes", r["reason"])
        self.assertEqual(read(self.calc), dirty.encode())
        self.assertTrue(os.path.islink(os.path.join(self.repo, "link.py")))

    def go_module(self):
        write(os.path.join(self.repo, "sum.go"), "package calc\n\nfunc Sum(a, b int) int { return a + b }\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "go")
        return os.path.join(self.repo, "sum.go")

    def test_go_mutant_overlays_through_a_wrapper(self):
        path = self.go_module()
        st, before = os.stat(path), read(path)
        # Stands in for a wrapper such as make: it sees only GOFLAGS and reports a compile failure.
        wrapper = [sys.executable, "-c", "import json, os, re, sys\n"
                   "o = re.search(r'-overlay=(\\S+)', os.environ['GOFLAGS']).group(1)\n"
                   "[copy] = set(json.load(open(o))['Replace'].values())\n"
                   "print(open(copy).read())\n"
                   "print('FAIL\\tex [build failed]' if 'a +)' in open(copy).read() else '--- FAIL: TestSum')\n"
                   "sys.exit(1)"]
        out = self.results({"test": wrapper, "mutants": [
            {"name": "minus", "file": "sum.go", "old": "a + b", "new": "a - b"},
            {"name": "broken", "file": "sum.go", "old": "a + b", "new": "a +)"},
        ]}, "--no-baseline", code=1)
        self.assertEqual([(r["verdict"], r["mode"]) for r in out], [("killed", "overlay"), ("build-error", "overlay")])
        self.assertIn("a - b", read(out[0]["log"]).decode())
        self.assertEqual((read(path), os.stat(path).st_mtime_ns), (before, st.st_mtime_ns))

    def test_explicit_overlay_refuses_a_non_go_file_instead_of_writing_it(self):
        r = self.one({"name": "m", "file": "calc.py", "old": "a + b", "new": "a - b", "mode": "overlay"}, code=2)
        self.assertEqual((r["verdict"], r["mode"]), ("invalid", "overlay"))
        self.assertIn("only .go files", r["reason"])
        self.assertEqual(read(self.calc), CALC.encode())

    def test_mixed_go_and_python_mutant_runs_in_place_and_reads_go_build_errors(self):
        path = self.go_module()
        seen = os.path.join(self.tmp, "seen")
        # Stands in for go build: it sees the mutant in the worktree and prints a compile error for it.
        fake = [sys.executable, "-c", "import os, shutil, sys\n"
                "assert '-overlay' not in os.environ.get('GOFLAGS', '')\n"
                "shutil.copy('sum.go', sys.argv[1])\n"
                "if 'a +)' in open('sum.go').read():\n"
                "    print('# ex\\n./sum.go:3:31: syntax error: unexpected )')\n"
                "else:\n"
                "    print('--- FAIL: TestSum (0.00s)')\n"
                "sys.exit(1)", seen]
        out = self.results({"test": fake, "mutants": [
            {"name": "broken", "files": [{"file": "sum.go", "old": "a + b", "new": "a +)"},
                                         {"file": "calc.py", "old": "a + b", "new": "a - b"}]},
            {"name": "minus", "files": [{"file": "sum.go", "old": "a + b", "new": "a - b"},
                                        {"file": "calc.py", "old": "x * 2", "new": "x * 3"}]},
        ]}, "--no-baseline", code=1)
        self.assertEqual([(r["verdict"], r["mode"]) for r in out], [("build-error", "in-place"), ("killed", "in-place")])
        self.assertIn(b"a - b", read(seen))
        self.assertIn(b"a + b", read(path))
        self.assertEqual(read(self.calc), CALC.encode())

    def test_python_mutant_with_go_words_in_a_shell_test_runs_in_place(self):
        test = "echo 'go test ./...' >/dev/null; %s check.py" % sys.executable
        [r] = self.results({"test": test, "mutants": [{"name": "minus", "file": "calc.py", "old": "a + b",
                                                       "new": "a - b"}]}, code=0)
        self.assertEqual((r["verdict"], r["mode"]), ("killed", "in-place"))
        self.assertEqual(read(self.calc), CALC.encode())

    def test_auto_mode_follows_the_changed_files(self):
        def mode(*files, test="go test ./..."):
            return mutate.resolve_mode({"mode": "auto", "test": test, "changes": [{"file": f} for f in files]})
        self.assertEqual(mode("a.go"), "overlay")
        self.assertEqual(mode("a.go", "a_test.go", test="make test"), "overlay")
        self.assertEqual(mode("a.go", test=["bash", "-co", "pipefail", "-c", "go test ."]), "overlay")
        self.assertEqual(mode("a.go", "a.py"), "in-place")
        self.assertEqual(mode("a.py", test="go test ./..."), "in-place")
        self.assertEqual(mode("go.mod"), "in-place")

    def test_overlay_run_waits_for_an_in_place_run(self):
        path = self.go_module()
        marker, release = os.path.join(self.tmp, "started"), os.path.join(self.tmp, "release")
        hold = [sys.executable, "-c", "import os, sys, time\nopen(sys.argv[1], 'w').close()\n"
                "while not os.path.exists(sys.argv[2]):\n    time.sleep(0.02)\nsys.exit(1)", marker, release]
        show = [sys.executable, "-c", "import json, os, re, sys\n"
                "o = re.search(r'-overlay=(\\S+)', os.environ['GOFLAGS']).group(1)\n"
                "[copy] = set(json.load(open(o))['Replace'].values())\n"
                "print(open(copy).read()); print('--- FAIL: TestSum'); sys.exit(1)"]
        first = {"test": hold, "mode": "in-place",
                 "mutants": [{"name": "a", "file": "sum.go", "old": "a + b", "new": "a * b"}]}
        second = {"test": show,
                  "mutants": [{"name": "b", "file": "sum.go", "old": "a + b", "new": "a - b"}]}
        procs = []
        for spec in (first, second):
            p = subprocess.Popen([sys.executable, SCRIPT, "--no-baseline", "--json", "--keep", "-"], cwd=self.repo,
                                 env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
            p.stdin.write(json.dumps(spec))
            p.stdin.close()
            procs.append(p)
            deadline = time.monotonic() + 30
            while not os.path.exists(marker):
                self.assertLess(time.monotonic(), deadline, "the first run never started")
                time.sleep(0.05)
        time.sleep(1)
        self.assertIsNone(procs[1].poll(), "the overlay run did not wait for the in-place run")
        write(release, "")
        outs = []
        for p in procs:
            p.wait(60)
            out, err = p.stdout.read(), p.stderr.read()
            p.stdout.close()
            p.stderr.close()
            self.assertEqual(p.returncode, 0, out + err)
            outs.append(json.loads(out)[0])
        self.assertIn("waiting for another in-place run", err)
        log = read(outs[1]["log"]).decode()
        self.assertIn("a - b", log)
        self.assertNotIn("a * b", log)
        self.assertIn(b"a + b", read(path))

    def test_signal_during_spawn_still_stops_the_command(self):
        real = subprocess.Popen
        started = []

        def popen(*a, **kw):
            proc = real(*a, **kw)
            started.append(proc)
            os.kill(os.getpid(), signal.SIGTERM)
            return proc

        old = signal.signal(signal.SIGTERM, mutate.on_signal)
        self.addCleanup(signal.signal, signal.SIGTERM, old)
        mutate._interrupted = None
        self.addCleanup(setattr, mutate, "_interrupted", None)
        subprocess.Popen = popen
        try:
            with self.assertRaises(mutate.Interrupted):
                mutate.run([sys.executable, "-c", "import time; time.sleep(60)"], self.repo, None,
                           os.path.join(self.tmp, "log"))
        finally:
            subprocess.Popen = real
        [proc] = started
        self.assertIsNotNone(proc.poll(), "the command outlived the interrupted run")

    def test_stop_group_reaps_the_child_when_the_group_probe_reports_eperm(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
        self.addCleanup(proc.wait)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        real = os.killpg

        def killpg(pid, sig):
            if sig == 0:
                raise PermissionError(errno.EPERM, "zombie-only group")
            real(pid, sig)

        mutate.os.killpg = killpg
        try:
            mutate.stop_group(proc)
        finally:
            mutate.os.killpg = real
        self.assertIsNotNone(proc.poll(), "stop_group returned before reaping the child")

    def test_command_that_cannot_start_names_the_command(self):
        log = os.path.join(self.tmp, "log")
        with self.assertRaises(mutate.Invalid) as e:
            mutate.run("echo hello there", os.path.join(self.tmp, "missing"), None, log)
        self.assertIn("echo hello there", str(e.exception))
        r = self.one({"name": "m", "file": "calc.py", "old": "a + b", "new": "a - b",
                      "test": ["no-such-binary-for-mutate-test"]}, "--no-baseline", code=2)
        self.assertIn("cannot run no-such-binary-for-mutate-test", r["reason"])
        self.assertEqual(read(self.calc), CALC.encode())

    def test_untracked_file_is_refused_in_place(self):
        write(os.path.join(self.repo, "extra.py"), "X = 1\n")
        r = self.one({"name": "x", "file": "extra.py", "old": "1", "new": "2"}, code=2)
        self.assertIn("uncommitted changes", r["reason"])

    def test_exit_codes(self):
        kill = {"name": "kill", "file": "calc.py", "old": "a + b", "new": "a - b"}
        survive = {"name": "survive", "file": "calc.py", "old": "x * 2", "new": "x * 3"}
        bad = {"name": "bad", "file": "calc.py", "old": "zzz", "new": "y"}
        self.mutate({"test": TEST, "mutants": [kill]}, code=0)
        self.mutate({"test": TEST, "mutants": [kill, survive]}, code=1)
        self.mutate({"test": TEST, "mutants": [kill, survive, bad]}, code=2)

    def test_spec_errors_exit_2(self):
        kill = {"name": "kill", "file": "calc.py", "old": "a + b", "new": "a - b"}
        for spec, msg in [
            ({"mutants": [kill]}, "no test command"),
            ({"test": TEST, "mutants": []}, "non-empty list"),
            ({"test": TEST, "mutants": [kill, kill]}, "duplicate name"),
            ({"test": TEST, "mutants": [{"name": "x", "file": "calc.py", "rev": "HEAD", "old": "a", "new": "b"}]},
             "either rev or old"),
            ({"test": TEST, "mutants": [{"name": "x", "file": "calc.py", "old": "a"}]}, "both be strings"),
            ({"test": TEST, "mode": "sideways", "mutants": [kill]}, "mode must be"),
            ({"test": TEST, "mode": [], "mutants": [kill]}, "mode must be"),
            ({"test": TEST, "mutants": [dict(kill, mode={})]}, "mode must be"),
            ({"test": 5, "mutants": [kill]}, "argv list or shell string"),
            ({"test": TEST, "cwd": "nope", "mutants": [kill]}, "not a directory"),
        ]:
            p = self.mutate(spec, code=2)
            self.assertIn(msg, p.stderr)
            self.assertEqual(p.stdout, "")
        p = subprocess.run([sys.executable, SCRIPT, "-"], input="{", text=True, capture_output=True, cwd=self.repo)
        self.assertEqual(p.returncode, 2)
        self.assertIn("not valid JSON", p.stderr)

    def test_json_output(self):
        out = self.results({"test": TEST, "mutants": [
            {"name": "kill", "file": "calc.py", "old": "a + b", "new": "a - b"},
            {"name": "survive", "file": "calc.py", "old": "x * 2", "new": "x * 3"},
        ]}, code=1)
        self.assertEqual([(r["name"], r["verdict"], r["exit"]) for r in out],
                         [("kill", "killed", 1), ("survive", "survived", 0)])
        for r in out:
            self.assertEqual(r["files"], ["calc.py"])
            self.assertEqual(r["test"], TEST)
            self.assertTrue(os.path.isfile(r["log"]), r["log"])
        self.assertIn("add is wrong", read(out[0]["log"]).decode())

    def test_text_output_one_line_per_mutant(self):
        p = self.mutate({"test": TEST, "mutants": [
            {"name": "kill", "file": "calc.py", "old": "a + b", "new": "a - b"},
            {"name": "bad", "file": "calc.py", "old": "zzz", "new": "y"},
        ]}, code=2)
        lines = p.stdout.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("killed") and " kill " in lines[0], lines[0])
        self.assertTrue(lines[1].startswith("invalid") and "old not found" in lines[1], lines[1])

    def test_failing_baseline_makes_mutants_invalid(self):
        write(self.calc, BUGGY + "\n\ndef double(x):\n    return x * 2\n")
        git(self.repo, "commit", "-q", "-am", "break")
        r = self.one({"name": "triple", "file": "calc.py", "old": "x * 2", "new": "x * 3"}, code=2)
        self.assertEqual(r["verdict"], "invalid")
        self.assertIn("baseline", r["reason"])
        r = self.one({"name": "triple", "file": "calc.py", "old": "x * 2", "new": "x * 3"}, "--no-baseline", code=0)
        self.assertEqual(r["verdict"], "killed")

    def test_shell_command_not_found_is_invalid(self):
        r = self.one({"name": "m", "file": "calc.py", "old": "a + b", "new": "a - b",
                      "test": "no-such-command-for-mutate-test"}, "--no-baseline", code=2)
        self.assertIn("command not found", r["reason"])
        self.assertEqual(read(self.calc), CALC.encode())

    def test_go_words_inside_a_non_shell_argument_stay_in_place(self):
        test = [sys.executable, "-c", "import calc; assert calc.add(2, 3) == 5, 'go test example failed'"]
        [r] = self.results({"test": test, "mutants": [{"name": "minus", "file": "calc.py", "old": "a + b",
                                                       "new": "a - b"}]}, code=0)
        self.assertEqual((r["verdict"], r["mode"]), ("killed", "in-place"))
        self.assertEqual(read(self.calc), CALC.encode())

    def test_shell_string_command(self):
        r = self.one({"name": "m", "file": "calc.py", "old": "a + b", "new": "a - b",
                      "test": "%s check.py" % sys.executable}, code=0)
        self.assertEqual(r["verdict"], "killed")

    def test_temp_scratch_removed_when_all_killed_unless_kept(self):
        kill = {"name": "kill", "file": "calc.py", "old": "a + b", "new": "a - b"}
        p = self.mutate({"test": TEST, "mutants": [kill]}, code=0)
        self.assertEqual(os.listdir(self.scratch_root), [])
        self.assertNotIn("log", p.stdout)
        [r] = self.results({"test": TEST, "mutants": [kill]}, "--keep", code=0)
        self.assertTrue(os.path.isfile(r["log"]))
        self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(r["log"]), "backup", "0-calc.py")))

    def test_out_dir_is_used_and_kept(self):
        out = os.path.join(self.tmp, "out")
        [r] = self.results({"test": TEST, "mutants": [{"name": "kill", "file": "calc.py", "old": "a + b",
                                                       "new": "a - b"}]}, "--out", out, code=0)
        self.assertEqual(os.path.dirname(os.path.dirname(r["log"])), out)
        self.assertTrue(os.path.isfile(r["log"]))


class ClassifyTest(unittest.TestCase):
    def test_non_go_nonzero_is_killed(self):
        self.assertEqual(mutate.classify(1, "anything", False)[0], "killed")
        self.assertEqual(mutate.classify(1, "# ex\n./a.go:5:2: undefined: x\nFAIL\tex [build failed]\n", False)[0],
                         "killed")
        self.assertEqual(mutate.classify(0, "--- FAIL", True)[0], "survived")

    def test_go_outputs(self):
        cases = [
            ("--- FAIL: TestSum (0.00s)\n    sum_test.go:9: got 4\nFAIL\nFAIL\tex/calc\t0.2s\nFAIL\n", "killed"),
            ("go: downloading example.com/x v1.0.0\n--- FAIL: TestSum (0.00s)\nFAIL\n", "killed"),
            ("panic: boom\n\ngoroutine 1 [running]:\nFAIL\tex/calc\t0.1s\n", "killed"),
            ("# ex/calc\ncalc/sum.go:4:9: syntax error\nFAIL\tex/calc [build failed]\n", "build-error"),
            ("FAIL\tex/calc [setup failed]\n", "build-error"),
            ("go: cannot find main module\n", "build-error"),
            ("--- FAIL: TestA\nFAIL\tex/a\t0.1s\nFAIL\tex/b [build failed]\n", "build-error"),
            ("# ex/p\np/a.go:3:26: syntax error: unexpected ), expected expression\n", "build-error"),
            ("found packages p (a.go) and q (b.go) in /x/p\n", "build-error"),
            ("p/c.go:2:8: package nope/x is not in std\n", "build-error"),
            ("go test ./calc\nmake: *** [Makefile:2: test] Error 1\n", "killed"),
            ("    sum_test.go:9: got 4\nexit status 1\n", "killed"),
            ("go: downloading example.com/x v1.0.0\nAssertionError\n", "killed"),
        ]
        for output, want in cases:
            self.assertEqual(mutate.classify(1, output, True)[0], want, output)

    def test_go_vet_output(self):
        # A vet finding and a compile error print the same diagnostic, so both are build-error.
        self.assertEqual(mutate.classify(1, "# ex/p\np/a.go:5:24: fmt.Printf format %d has arg\n", True)[0],
                         "build-error")
        self.assertEqual(mutate.classify(1, "# ex/p\nvet: p/a.go:3:23: undefined: x\n", True)[0], "build-error")
        self.assertEqual(mutate.classify(1, "# ex/p\n# [ex/p]\np/a_test.go:3:35: Logf format %d\n"
                                            "FAIL\tex/p [build failed]\n", True)[0], "build-error")


@unittest.skipUnless(shutil.which("go"), "go is not on PATH")
class GoOverlayTest(unittest.TestCase):
    SUM = "package calc\n\nfunc Sum(a, b int) int {\n\treturn a + b\n}\n\nfunc Untested() int {\n\treturn 1\n}\n"
    SUM_TEST = ('package calc\n\nimport "testing"\n\nfunc TestSum(t *testing.T) {\n'
                '\tif got := Sum(2, 3); got != 5 {\n\t\tt.Fatalf("Sum(2, 3) = %d", got)\n\t}\n}\n')

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="mutate-go-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, "calc"))
        git(self.repo, "init", "-q", "-b", "main")
        write(os.path.join(self.repo, "go.mod"), "module example.com/m\n\ngo 1.21\n")
        self.sum = os.path.join(self.repo, "calc", "sum.go")
        write(self.sum, self.SUM.replace("a + b", "a - b"))
        write(os.path.join(self.repo, "calc", "sum_test.go"), self.SUM_TEST)
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "buggy")
        write(self.sum, self.SUM)
        git(self.repo, "commit", "-q", "-am", "fix")
        self.env = dict(os.environ, GOFLAGS="", GOTOOLCHAIN="local", GOWORK="off")

    def run_spec(self, mutants, code, cwd=None, env=None, test=None, watch=None):
        spec = {"test": test or ["go", "test", "./calc"], "mutants": mutants}
        watch = watch or self.sum
        st = os.stat(watch)
        before = (read(watch), st.st_mtime_ns, st.st_ino)
        p = subprocess.run([sys.executable, SCRIPT, "--json", "--keep", "-"], input=json.dumps(spec), text=True,
                           capture_output=True, cwd=cwd or self.repo, env=env or self.env, timeout=300)
        self.assertEqual(p.returncode, code, "stdout: %s\nstderr: %s" % (p.stdout, p.stderr))
        st = os.stat(watch)
        self.assertEqual((read(watch), st.st_mtime_ns, st.st_ino), before, "the worktree file changed")
        return json.loads(p.stdout)

    def test_syntax_error_is_build_error_behind_any_wrapper(self):
        makefile = os.path.join(self.tmp, "Makefile")
        write(makefile, "test:\n\tgo test ./calc\n")
        commands = [("go test", ["go", "test", "./calc"]),
                    ("go -C", ["go", "-C", self.repo, "test", "./calc"]),
                    ("bash -co", ["bash", "-co", "pipefail", "-c", "go test ./calc | cat"])]
        if shutil.which("make"):
            commands.append(("make", ["make", "-s", "-f", makefile, "test"]))
        if shutil.which("zsh"):
            commands.append(("zsh", ["zsh", "-oerrexit", "-c", "go test ./calc; exit $?"]))
        for label, test in commands:
            out = self.run_spec([
                {"name": "minus", "file": "calc/sum.go", "old": "a + b", "new": "a - b"},
                {"name": "broken", "file": "calc/sum.go", "old": "a + b", "new": "a +"},
            ], 1, test=test)
            self.assertEqual([(r["verdict"], r["mode"]) for r in out],
                             [("killed", "overlay"), ("build-error", "overlay")], label)

    def test_mixed_go_and_python_mutant_runs_in_place(self):
        helper = os.path.join(self.repo, "calc", "helper.py")
        write(helper, "X = 1\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "helper")
        spec = {"test": ["go", "test", "./calc"], "mutants": [
            {"name": "broken", "files": [{"file": "calc/sum.go", "old": "a + b", "new": "a +"},
                                         {"file": "calc/helper.py", "old": "1", "new": "2"}]},
            {"name": "minus", "files": [{"file": "calc/sum.go", "old": "a + b", "new": "a - b"},
                                        {"file": "calc/helper.py", "old": "1", "new": "2"}]}]}
        p = subprocess.run([sys.executable, SCRIPT, "--json", "-"], input=json.dumps(spec), text=True,
                           capture_output=True, cwd=self.repo, env=self.env, timeout=300)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual([(r["verdict"], r["mode"]) for r in json.loads(p.stdout)],
                         [("build-error", "in-place"), ("killed", "in-place")])
        self.assertEqual(read(self.sum), self.SUM.encode())
        self.assertEqual(read(helper), b"X = 1\n")

    def test_overlay_kills_without_touching_worktree(self):
        [r] = self.run_spec([{"name": "minus", "file": "calc/sum.go", "old": "a + b", "new": "a - b"}], 0)
        self.assertEqual((r["verdict"], r["mode"]), ("killed", "overlay"))
        self.assertIn("Sum(2, 3) = -1", read(r["log"]).decode())

    def test_overlay_from_symlinked_shell_directory(self):
        link = os.path.join(self.tmp, "link")
        os.symlink(self.repo, link)
        [r] = self.run_spec([{"name": "minus", "file": "calc/sum.go", "old": "a + b", "new": "a - b"}], 0,
                            cwd=link, env=dict(self.env, PWD=link))
        self.assertEqual((r["verdict"], r["mode"]), ("killed", "overlay"))

    def test_overlay_rev_mutant_on_dirty_file(self):
        dirty = self.SUM + "\n// local edit\n"
        write(self.sum, dirty)
        [r] = self.run_spec([{"name": "fix-reverted", "file": "calc/sum.go", "rev": "HEAD~1"}], 0)
        self.assertEqual((r["verdict"], r["mode"]), ("killed", "overlay"))

    def test_overlay_survived_and_build_error(self):
        out = self.run_spec([
            {"name": "untested", "file": "calc/sum.go", "old": "return 1", "new": "return 2"},
            {"name": "broken", "file": "calc/sum.go", "old": "a + b", "new": "a +"},
        ], 1)
        self.assertEqual([(r["name"], r["verdict"]) for r in out], [("untested", "survived"), ("broken", "build-error")])


if __name__ == "__main__":
    unittest.main()
