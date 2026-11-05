import os
import subprocess
import sys
import tempfile
import time
import unittest

HEAVY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "heavy.py")


class HeavyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "log")
        self.env = {**os.environ, "XDG_STATE_HOME": self.tmp.name, "HWORKS_HEAVY_SLOTS": "1"}
        self.env.pop("HWORKS_HEAVY_HELD", None)

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, script):
        return subprocess.Popen([sys.executable, HEAVY, "sh", "-c", script], env=self.env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

    def lines(self):
        with open(self.log, encoding="utf-8") as f:
            return f.read().split()

    def test_one_slot_runs_commands_one_at_a_time(self):
        body = f"echo start >> {self.log}; sleep 0.4; echo end >> {self.log}"
        procs = [self.start(body) for _ in range(3)]
        for p in procs:
            p.communicate(timeout=20)
            self.assertEqual(p.returncode, 0)
        self.assertEqual(self.lines(), ["start", "end"] * 3)

    def test_a_backgrounded_child_keeps_the_slot(self):
        first = self.start(f"(sleep 0.6; echo bg-done >> {self.log}) & exit 0")
        time.sleep(0.2)
        second = self.start(f"echo second >> {self.log}")
        first.communicate(timeout=20)
        err = second.communicate(timeout=20)[1]
        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertEqual(self.lines(), ["bg-done", "second"])
        self.assertIn("slots busy", err)

    def test_killing_heavy_ends_its_command_before_the_slot_frees(self):
        first = self.start(f"python3 -c 'import time; time.sleep(1.5)'; echo first-done >> {self.log}")
        time.sleep(0.4)
        first.kill()
        first.wait(timeout=20)
        first.stderr.close()
        second = self.start(f"echo second >> {self.log}")
        second.communicate(timeout=20)
        time.sleep(1.6)
        self.assertEqual(self.lines(), ["second"])

    def test_background_work_past_the_drain_window_is_terminated(self):
        self.env["HWORKS_HEAVY_DRAIN_S"] = "1"
        start = time.monotonic()
        first = self.start(f"(sleep 30; echo late >> {self.log}) & exit 0")
        err = first.communicate(timeout=20)[1]
        self.assertLess(time.monotonic() - start, 15)
        self.assertIn("terminating it", err)
        second = self.start(f"echo second >> {self.log}")
        second.communicate(timeout=20)
        self.assertEqual(self.lines(), ["second"])

    def test_nested_run_does_not_wait_for_its_parent_and_keeps_the_status(self):
        p = subprocess.run([sys.executable, HEAVY, sys.executable, HEAVY, "sh", "-c", "exit 7"],
                           env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 7, p.stderr)


if __name__ == "__main__":
    unittest.main()
