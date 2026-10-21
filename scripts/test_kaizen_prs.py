import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "kaizen-prs.py")
FAKE_GH = os.path.join(HERE, "testdata", "kaizen-prs", "fake-gh.sh")

spec = importlib.util.spec_from_file_location("kaizen_prs", SCRIPT)
kp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kp)

SINCE = datetime(2026, 1, 1, tzinfo=timezone.utc)
CHILD = "m1/0b8e3c2a-1111-2222-3333-444455556666/run-0/session.jsonl"
PR1 = "https://github.com/acme/app/pull/1"
PR2 = "https://github.com/acme/app/pull/2"
PR3 = "https://github.com/acme/app/pull/3"
BAD = "https://git.example.com/x/y/pull/9"


def call(ts, cid, name, args):
    return {"type": "message", "timestamp": f"2026-10-01T{ts}Z",
            "message": {"role": "assistant", "content": [{"type": "toolCall", "id": cid, "name": name,
                                                          "arguments": args}]}}


def result(ts, cid, name, text="ok"):
    return {"type": "message", "timestamp": f"2026-10-01T{ts}Z",
            "message": {"role": "toolResult", "toolCallId": cid, "toolName": name,
                        "content": [{"type": "text", "text": text}]}}


def say(ts, role, text):
    return {"type": "message", "timestamp": f"2026-10-01T{ts}Z",
            "message": {"role": role, "content": [{"type": "text", "text": text}]}}


SESSIONS = {
    "m1.jsonl": [
        say("10:00:00", "user", "open a PR"),
        call("10:00:30", "c1", "bash", {"command": "git push -u origin x && gh pr create --draft --title T"}),
        result("10:01:30", "c1", "bash", f"Creating pull request\n{PR1}\n"),
        say("10:02:00", "assistant", "done"),
        say("10:12:00", "user", "thanks"),
        call("10:12:10", "c2", "read", {"path": "a.go"}),
        result("10:12:15", "c2", "read"),
        call("11:00:00", "c3", "bash", {"command": f"gh pr view {BAD} --json state"}),
        result("11:00:10", "c3", "bash"),
    ],
    CHILD: [
        call("10:00:00", "k1", "bash", {"command": f"gh pr checks {PR1}"}),
        result("10:00:20", "k1", "bash"),
        call("10:00:20", "k2", "track_pr", {"url": PR2}),
        result("10:00:25", "k2", "track_pr"),
    ],
    "p1.jsonl": [
        call("10:00:00", "c1", "bash", {"command": "git push origin feat"}),
        result("10:00:03", "c1", "bash", " * [new branch]      feat -> feat"),
    ],
    "s1.jsonl": [
        call("10:00:00", "c1", "bash", {"command": "gh pr create --fill"}),
        result("10:00:05", "c1", "bash", f"Creating...\n{PR3}"),
        say("10:05:05", "user", "[automation] ping"),
        say("10:05:15", "assistant", "pong"),
        say("10:06:15", "user", "real question"),
    ],
}


class KaizenPrs(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        for rel, entries in SESSIONS.items():
            path = os.path.join(self.d, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(json.dumps({"type": "session", "id": rel, "cwd": "/w/app"}) + "\n")
                for e in entries:
                    f.write(json.dumps(e) + "\n")

    def analyze(self, **kw):
        report, _ = kp.analyze({"sessions": self.d}, SINCE, gh=FAKE_GH, pr_tools={"track_pr"},
                               skip=re.compile(r"^\[automation\]"), **kw)
        return report

    def test_links_and_coverage(self):
        c = self.analyze()["coverage"]
        self.assertEqual((c["sessions_main"], c["sessions_child"], c["sessions_linked"]), (3, 1, 3))
        self.assertEqual(c["links_by_role"], {"opened": 2, "touched": 3})
        self.assertEqual(c["prs_found"], 4)
        self.assertEqual(c["fetch"], {
            "git.example.com": {"fetched": 0, "failed": 1, "error": "error connecting to git.example.com"},
            "github.com": {"fetched": 3, "failed": 0, "error": None}})
        self.assertEqual(c["pushed_without_link"], ["p1.jsonl"])

    def test_outcomes_ranked_by_rework(self):
        o = self.analyze()["outcomes"]
        self.assertEqual((o["merged"], o["closed_unmerged"], o["open"], o["draft"]), (2, 0, 1, 1))
        self.assertEqual([r["url"] for r in o["rows"]], [PR1, PR3, PR2])
        top = o["rows"][0]
        self.assertEqual(top["opened_by"], "m1.jsonl")
        self.assertEqual(top["other_sessions"], [CHILD])
        self.assertEqual((top["commits_after_create"], top["changes_requested"], top["failing_checks"],
                          top["rework"]), (2, 1, ["lint"], 4))
        self.assertEqual(top["pending_checks"], ["deploy"])
        self.assertEqual(top["feedback_bodies"], 2)
        self.assertEqual((top["hours_to_first_review"], top["hours_to_close"], top["hours_last_commit_to_merge"]),
                         (2.0, 24.0, 2.0))
        self.assertEqual(o["rows"][2]["opened_by"], None)
        self.assertEqual(o["unfetched"], [{"url": BAD, "opened_by": None, "other_sessions": ["m1.jsonl"]}])

    def test_test_ratio_leads(self):
        leads = {t["url"]: t["leads"] for t in self.analyze()["tests"]}
        self.assertEqual(leads, {
            PR1: ["tests > 2x production lines"],
            PR2: ["tests > 2x production lines", "production < 10 lines, tests > 50"],
            PR3: []})

    def test_time_split(self):
        t = self.analyze()["time"]
        main = t["transcripts"]["main_total"]
        self.assertEqual(main, {"model": 80, "tool": 83, "tools": {"bash": 78, "read": 5}, "human": 660,
                                "harness": 300, "idle": 2865,
                                "latency": {"bash": {"count": 4, "total": 78, "median": 7.5},
                                            "read": {"count": 1, "total": 5, "median": 5}}})
        self.assertEqual(t["transcripts"]["child_total"],
                         {"model": 0, "tool": 25, "tools": {"bash": 20, "track_pr": 5}, "human": 0,
                          "harness": 0, "idle": 0,
                          "latency": {"bash": {"count": 1, "total": 20, "median": 20},
                                      "track_pr": {"count": 1, "total": 5, "median": 5}}})
        self.assertEqual(t["gh"], {"median_hours_to_first_review": 1.5, "median_hours_to_close": 13.0,
                                   "median_hours_last_commit_to_merge": 2.5, "median_ci_span_hours": 0.75,
                                   "prs": 3})

    def write(self, rel, entries):
        path = os.path.join(self.d, rel)
        with open(path, "w") as f:
            f.write("".join(json.dumps(e) + "\n" for e in entries))
        return kp.read_session(path, SINCE, set(), [])

    def test_batched_calls_latency(self):
        batch = {"type": "message", "timestamp": "2026-10-01T10:00:00Z",
                 "message": {"role": "assistant", "content": [
                     {"type": "toolCall", "id": "a", "name": "read", "arguments": {"path": "x"}},
                     {"type": "toolCall", "id": "b", "name": "bash", "arguments": {"command": "make"}}]}}
        s = self.write("batch.jsonl", [batch, result("10:00:10", "a", "read"), result("10:00:30", "b", "bash")])
        sp = kp.summarize_latency(kp.time_split(s["messages"], None))
        self.assertEqual(sp["latency"], {"bash": {"count": 1, "total": 30, "median": 30},
                                         "read": {"count": 1, "total": 10, "median": 10}})
        self.assertEqual(sp["tools"], {"read": 10, "bash": 20})
        self.assertEqual(sum(sp[k] for k in ("model", "tool", "human", "harness", "idle")), 30)

    def test_push_to_default_branch_is_not_a_gap(self):
        def pushed(cmd, out):
            return self.write("push.jsonl", [call("10:00:00", "p", "bash", {"command": cmd}),
                                             result("10:00:01", "p", "bash", out)])["pushed"]
        self.assertEqual([
            pushed("git push", "To github.com:a/b.git\n   1a2b3c4..5d6e7f8  main -> main"),
            pushed("git push", "To github.com:a/b.git\n   1a2b3c4..5d6e7f8  feat -> feat"),
            pushed("git push -u origin x", "To github.com:a/b.git\n * [new branch]      x -> x"),
            pushed("git push origin HEAD:refs/heads/trunk", "Everything up-to-date"),
            pushed("git push origin HEAD:topic && echo ok", "error: failed to push some refs"),
            pushed("git -C repo push", "fatal: no upstream"),
            pushed("git push -q -o ci.skip origin main", ""),
            pushed("git push --push-option ci.skip origin feat", ""),
        ], [False, True, True, False, True, True, False, True])

    def test_closed_draft_is_not_draft(self):
        gh_dir = os.path.join(self.d, "gh")
        shutil.copytree(os.path.dirname(FAKE_GH), gh_dir)
        with open(os.path.join(gh_dir, "pr-2.json")) as f:
            pr2 = json.load(f)
        with open(os.path.join(gh_dir, "pr-2.json"), "w") as f:
            json.dump({**pr2, "state": "CLOSED", "isDraft": True}, f)
        report, _ = kp.analyze({"sessions": self.d}, SINCE, gh=os.path.join(gh_dir, "fake-gh.sh"),
                               pr_tools={"track_pr"})
        o = report["outcomes"]
        self.assertEqual((o["merged"], o["closed_unmerged"], o["open"], o["draft"]), (1, 1, 1, 1))

    def test_cli_no_fetch(self):
        env = {**os.environ, "HWORKS_PI_SESSIONS": self.d, "HWORKS_GH": "/nonexistent/gh",
               "HWORKS_PR_TOOLS": "track_pr"}
        p = subprocess.run([sys.executable, SCRIPT, "--since", "2026-01-01", "--no-fetch", "--json"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["coverage"]["fetch"], "skipped (--no-fetch)")
        self.assertEqual(out["coverage"]["prs_found"], 4)
        self.assertEqual(out["outcomes"]["rows"], [])
        self.assertEqual([u["url"] for u in out["outcomes"]["unfetched"]], [BAD, PR1, PR2, PR3])

    def test_cli_text_and_missing_source(self):
        env = {**os.environ, "HWORKS_PI_SESSIONS": self.d, "HWORKS_GH": FAKE_GH}
        p = subprocess.run([sys.executable, SCRIPT, "--since", "2026-01-01"], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("git.example.com: 0 fetched, 1 failed  error: error connecting to git.example.com", p.stdout)
        self.assertIn(f"{PR1}  [MERGED] rework 4", p.stdout)
        self.assertIn("    tool latency (overlaps for batched calls): bash 4x total 0.0h median 7.5s, "
                      "read 1x total 0.0h median 5.0s\n", p.stdout)
        env["HWORKS_PI_SESSIONS"] = os.path.join(self.d, "nope")
        p = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("missing source: pi sessions: not found", p.stdout)


if __name__ == "__main__":
    unittest.main()
