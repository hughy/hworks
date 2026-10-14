import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "session-messages.py")


def transcript(path, cwd, messages):
    """messages: (role, timestamp, content) where content is a string or a content list."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [{"type": "session", "id": "x", "timestamp": "2026-10-01T10:00:00.000Z", "cwd": cwd}]
    for role, ts, content in messages:
        lines.append({"type": "message", "timestamp": ts, "message": {"role": role, "content": content}})
    with open(path, "w") as f:
        f.write("\n".join(json.dumps(x) for x in lines) + "\n")


class SessionMessages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        transcript(os.path.join(d, "--w-policy-demo--", "a.jsonl"), "/home/u/worktrees/Policy-Demo-fix", [
            ("user", "2026-10-02T09:00:00Z", [{"type": "text", "text": "build the encoder"}]),
            ("assistant", "2026-10-02T09:01:00Z", [{"type": "text", "text": "done"}]),
            ("user", "2026-10-02T09:05:00Z", "no, the caps are per sell token"),
            ("user", "2020-01-01T00:00:00Z", "too old"),
        ])
        transcript(os.path.join(d, "--w-policy-demo--", "a", "run-0", "session.jsonl"), "/home/u/worktrees/policy-demo",
                   [("user", "2026-10-02T09:02:00Z", "brief from the parent")])
        transcript(os.path.join(d, "--w-other--", "b.jsonl"), "/home/u/other",
                   [("user", "2026-10-03T09:00:00Z", "unrelated")])

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        env = dict(os.environ, HWORKS_PI_SESSIONS=self.tmp.name)
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=env, check=True)

    def rows(self, *args):
        return [json.loads(x) for x in self.run_script("--since", "2026-09-01", "--json", *args).stdout.splitlines()]

    def test_operator_messages_only_from_matching_top_level_sessions(self):
        rows = self.rows("--cwd-match", "policy-demo")
        self.assertEqual([r["text"] for r in rows], ["build the encoder", "no, the caps are per sell token"])
        self.assertEqual({r["session"] for r in rows}, {os.path.join("--w-policy-demo--", "a.jsonl")})

    def test_without_match_every_top_level_session_is_kept(self):
        self.assertEqual({r["text"] for r in self.rows()},
                         {"build the encoder", "no, the caps are per sell token", "unrelated"})

    def test_truncation_and_text_output(self):
        out = self.run_script("--since", "2026-09-01", "--cwd-match", "policy", "--max-chars", "5").stdout
        self.assertIn("cwd: /home/u/worktrees/Policy-Demo-fix", out)
        self.assertIn("build [...]", out)
        self.assertNotIn("brief from the parent", out)


if __name__ == "__main__":
    unittest.main()
