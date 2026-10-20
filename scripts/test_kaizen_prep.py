import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "kaizen-prep.py")

spec = importlib.util.spec_from_file_location("kaizen_prep", SCRIPT)
kp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kp)

FINDINGS = """# kaizen 2026-01-01
Window 14 days; thresholds 5/3/10.

- [1] K1 retry-helper | 12 sessions, 3 samples | coder | build tool, tests pass | units.json K1 | open
- [4] K2 pi-cache | 40k token-turns | user | raise cache bug | upstream:pi | awaiting-user
- [5] K3 task-dir guidance | 4 sessions | coder | AGENTS.md line | abc123 | implemented (merged, effect not yet seen)
- [2] K4 ignored-script | 6 sessions | coder | router line | def456 | effective
- [3] K5 bad-artifact | 3 sessions | /skill:correct | lint | ghi789 | unproven
- [investigate] K6 slow-review | rounds | reviewer | does round 3 find blockers? | none | pending
- [1] K7 another | 10 sessions | coder | tool | units.json K7 | open
- [drop] import json scripts | generic idiom
- [drop] gate runs | tool used as intended
- [5] K8 broken | only three | fields
- [5] K9 bad-state | ev | coder | edit | abc | done
- [1] K10 extra-pipe | ev | coder | run check | head -20 | abc | open
- [drop] missing-reason
"""


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


class Thresholds(unittest.TestCase):
    def test_skill_examples(self):
        self.assertEqual(kp.thresholds(3), {"group": 3, "blocker_mistake_guidance": 3, "new_tool": 3})
        self.assertEqual(kp.thresholds(14), {"group": 5, "blocker_mistake_guidance": 3, "new_tool": 10})
        self.assertEqual(kp.thresholds(28), {"group": 10, "blocker_mistake_guidance": 6, "new_tool": 20})

    def test_window_from_days(self):
        self.assertEqual(kp.window_days("28d"), 28)


class CarryOver(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        self.path = os.path.join(self.d, "findings-2026-01-01.md")
        with open(self.path, "w") as f:
            f.write(FINDINGS)

    def test_groups_counts_and_unparsed(self):
        by_state, unparsed, counts = kp.carry_over(self.path)
        ids = {s: [r["id"] for r in rows] for s, rows in by_state.items()}
        self.assertEqual(ids, {"open": ["K1", "K7"], "awaiting-user": ["K2"], "implemented": ["K3"],
                               "unproven": ["K5"], "pending": ["K6"]})
        self.assertEqual(by_state["open"][0], {"outcome": "1", "id": "K1", "group": "retry-helper",
                                               "deliverable": "build tool, tests pass",
                                               "artifact": "units.json K1"})
        self.assertEqual(by_state["implemented"][0]["id"], "K3")
        self.assertEqual(counts, {"carry_over": 6, "drop": 2, "effective": 1, "unparsed": 4})
        self.assertEqual([u["text"].split()[2] for u in unparsed], ["K8", "K9", "K10", "missing-reason"])

    def test_json_round_trips_and_default_discovery(self):
        older = os.path.join(self.d, "findings-2025-12-01.md")
        with open(older, "w") as f:
            f.write("- [1] OLD x | e | a | d | art | open\n")
        p = run("--since", "28d", "--task-dir", self.d, "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["window_days"], 28)
        self.assertEqual(out["thresholds"]["group"], 10)
        self.assertEqual(out["previous_file"], self.path)
        self.assertEqual(out["counts"]["drop"], 2)
        self.assertEqual(len(out["unparsed"]), 4)
        self.assertEqual(len(out["commands"]), 4)
        self.assertIn("--min-sessions 10", out["commands"][0])
        self.assertEqual(json.loads(json.dumps(out)), out)

    def test_text_lists_unparsed(self):
        p = run("--since", "14d", "--previous", self.path)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("== could not parse ==", p.stdout)
        self.assertIn("K8 broken", p.stdout)
        self.assertIn("== awaiting-user ==", p.stdout)

    def test_missing_previous_exits_2(self):
        p = run("--previous", os.path.join(self.d, "nope.md"))
        self.assertEqual(p.returncode, 2)
        self.assertIn("no such file", p.stderr)

    def test_empty_task_dir_says_none(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty)
        p = run("--task-dir", empty)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Previous findings: none", p.stdout)


if __name__ == "__main__":
    unittest.main()
