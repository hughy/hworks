import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "kaizen-prep.py")
FAKE_GH = os.path.join(HERE, "testdata", "kaizen-prs", "fake-gh.sh")

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


def run(*args, **env):
    env = {**os.environ, "HWORKS_GH": FAKE_GH, "HWORKS_PI_SESSIONS": os.devnull, **env}
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=env)


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
        self.assertEqual(len(out["commands"]), 5)
        self.assertIn("--min-sessions 10", out["commands"][0])
        self.assertIn('kaizen-prs.py --since 28d --top 40 > "$TASK_DIR/prs-', out["commands"][2])
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


class Sources(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)

    def touch(self, rel, days_ago):
        path = os.path.join(self.d, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        t = time.time() - days_ago * 86400
        os.utime(path, (t, t))
        return datetime.fromtimestamp(t, timezone.utc).date().isoformat()

    def test_session_counts_in_window(self):
        newest = self.touch("p/a.jsonl", 1)
        oldest = self.touch("p/b.jsonl", 5)
        self.touch("p/b/0b8e3c2a-1111-2222-3333-444455556666/run-0/session.jsonl", 2)
        self.touch("p/old.jsonl", 30)
        self.touch("subagent-artifacts/x.jsonl", 1)
        got = kp.session_files(self.d, kp.ks.parse_since("14d"))
        self.assertEqual(got, {"main": 2, "child": 1, "oldest": oldest, "newest": newest})

    def test_gh_auth_parse(self):
        with open(os.path.join(HERE, "testdata", "kaizen-prs", "auth-status.txt")) as f:
            hosts = kp.parse_gh_auth(f.read())
        self.assertEqual(hosts, {"github.com": "logged in",
                                 "git.example.com": "failed: The token in GH_TOKEN is invalid."})

    def test_text_sources_block(self):
        self.touch("p/a.jsonl", 1)
        p = run("--since", "14d", "--task-dir", self.d, HWORKS_PI_SESSIONS=self.d,
                HWORKS_HARNESS_AUDIT_LOG=os.path.join(self.d, "audit.log"))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(f"  sessions: found ({self.d})\n    jsonl modified in window: 1 main, 0 child", p.stdout)
        self.assertIn("  harness audit log: MISSING", p.stdout)
        self.assertIn("  gh github.com: logged in\n", p.stdout)
        self.assertIn("  gh git.example.com: failed: The token in GH_TOKEN is invalid.", p.stdout)
        self.assertIn("name it at the top of the findings file", p.stdout)
        self.assertLess(p.stdout.index("Sources:"), p.stdout.index("Reporters"))

    def test_no_gh_and_missing_gh(self):
        p = run("--task-dir", self.d, "--no-gh", "--json", HWORKS_GH="/nonexistent/gh")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["sources"]["gh"], {"checked": False})
        self.assertIn("gh: not checked (--no-gh)", run("--task-dir", self.d, "--no-gh").stdout)
        p = run("--task-dir", self.d, "--json", HWORKS_GH="/nonexistent/gh")
        self.assertEqual(json.loads(p.stdout)["sources"]["gh"],
                         {"checked": True, "hosts": {}, "not_configured": "/nonexistent/gh: not found"})


if __name__ == "__main__":
    unittest.main()
