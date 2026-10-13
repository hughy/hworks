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
        self.assertEqual(os.stat(self.calc).st_mtime_ns, 1_000_000_000_456)

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

    def test_overlay_mode_needs_a_go_command(self):
        r = self.one({"name": "m", "file": "calc.py", "old": "a + b", "new": "a - b", "mode": "overlay"},
                     "--no-baseline", code=2)
        self.assertIn("needs a go test", r["reason"])
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
        self.assertEqual(mutate.classify(1, "anything", set())[0], "killed")
        self.assertEqual(mutate.classify(0, "--- FAIL", {"test"})[0], "survived")

    def test_go_outputs(self):
        cases = [
            ("--- FAIL: TestSum (0.00s)\n    sum_test.go:9: got 4\nFAIL\nFAIL\tex/calc\t0.2s\nFAIL\n", "killed"),
            ("panic: boom\n\ngoroutine 1 [running]:\nFAIL\tex/calc\t0.1s\n", "killed"),
            ("# ex/calc\ncalc/sum.go:4:9: syntax error\nFAIL\tex/calc [build failed]\nFAIL\n", "build-error"),
            ("FAIL\tex/calc [setup failed]\n", "build-error"),
            ("go: cannot find main module\n", "build-error"),
            ("--- FAIL: TestA\nFAIL\tex/a\t0.1s\nFAIL\tex/b [build failed]\n", "build-error"),
        ]
        for output, want in cases:
            self.assertEqual(mutate.classify(1, output, {"test"})[0], want, output)

    def test_go_vet_and_build(self):
        self.assertEqual(mutate.classify(1, "# ex\n./a.go:5:2: Printf format %d\n", {"vet"})[0], "killed")
        self.assertEqual(mutate.classify(1, "# ex\nvet: ./a.go:5:2: undefined: x\n", {"vet"})[0], "build-error")
        self.assertEqual(mutate.classify(1, "# ex\n./a.go:5:2: undefined: x\n", {"build"})[0], "build-error")

    def test_go_subcommands(self):
        self.assertEqual(mutate.go_subcommands(["go", "test", "./..."]), {"test"})
        self.assertEqual(mutate.go_subcommands("cd x && /usr/local/go/bin/go vet ./... && go build ."),
                         {"vet", "build"})
        self.assertEqual(mutate.go_subcommands(["go", "-C", "/tmp/x", "test", "."]), {"test"})
        self.assertEqual(mutate.go_subcommands("go --C=sub vet ./..."), {"vet"})
        self.assertEqual(mutate.go_subcommands(["go", "-C", "test", "mod", "tidy"]), set())
        self.assertEqual(mutate.go_subcommands("make test"), set())
        self.assertEqual(mutate.go_subcommands(["python3", "-m", "pytest"]), set())


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

    def test_go_chdir_flag_still_uses_overlay(self):
        out = self.run_spec([
            {"name": "minus", "file": "calc/sum.go", "old": "a + b", "new": "a - b"},
            {"name": "broken", "file": "calc/sum.go", "old": "a + b", "new": "a +"},
        ], 1, test=["go", "-C", self.repo, "test", "./calc"])
        self.assertEqual([(r["verdict"], r["mode"]) for r in out], [("killed", "overlay"), ("build-error", "overlay")])

    def test_go_command_refuses_a_non_go_file_instead_of_writing_it(self):
        data = os.path.join(self.repo, "calc", "data.txt")
        write(data, "one\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "data")
        [r] = self.run_spec([{"name": "data", "file": "calc/data.txt", "old": "one", "new": "two"}], 2, watch=data)
        self.assertEqual((r["verdict"], r["mode"]), ("invalid", "overlay"))
        self.assertIn("only .go files", r["reason"])

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
