import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "retro-sessions.py")
FIXTURES = os.path.join(HERE, "testdata", "retro-sessions")
FIXTURE_SESSIONS = ["proj-a/2026-10-01_s1.jsonl", "proj-a/2026-10-02_s2.jsonl", "proj-b/2026-10-03_s3.jsonl"]

spec = importlib.util.spec_from_file_location("retro_sessions", SCRIPT)
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)


def source(**over):
    src = {"sessions": FIXTURES, "tasks": "/fake-tasks", "tmp": "/var/folders/x/T", "tool_dirs": []}
    src.update(over)
    return src


def run(since="2026-09-01", **over):
    return rs.analyze(source(**over), rs.parse_since(since), min_sessions=3, top=15)


def group(report, section, shape):
    found = [r for r in report[section] if r["shape"] == shape]
    return found[0] if found else None


class Normalize(unittest.TestCase):
    def shape(self, cmd):
        return [(w, s, sc, sorted(f)) for w, s, sc, f in rs.segments(cmd)]

    def test_quotes_paths_and_redirections_vanish(self):
        segs = self.shape("cd /w && GOFLAGS=-mod=mod go test -count=1 -overlay=\"$S/o.json\" ./x -run '^TestA$' 2>&1 | tail -5")
        self.assertEqual(segs, [("cd", (), (), []), ("go", ("test",), (), ["-count", "-overlay", "-run"]),
                                ("tail", (), (), [])])

    def test_interpreter_running_a_script_is_keyed_by_the_folded_script_name(self):
        self.assertEqual(self.shape("python3 ~/x/scripts/mut3.py /tmp/spec.json"), [("mutN.py", (), (), [])])

    def test_heredoc_body_is_not_shell(self):
        rest, docs = rs.split_heredocs("cat > /tmp/a.py <<'EOF'\nimport os\nprint(1)\nEOF\nnode /tmp/b.mjs")
        self.assertEqual(rest, "cat > /tmp/a.py <<'EOF'\nnode /tmp/b.mjs")
        self.assertEqual(docs, [("cat > /tmp/a.py <<'EOF'", "import os\nprint(1)")])

    def test_inline_interpreter_code_becomes_a_script(self):
        call = {"name": "bash", "args": {"command": "python3 -c 'import json\nd = json.load(f)\nprint(d)'"}}
        self.assertEqual([(s["lang"], s["code"]) for s in rs.call_scripts(call, source())],
                         [("py", "import json\nd = json.load(f)\nprint(d)")])

    def test_ordinary_shapes(self):
        self.assertTrue(rs.ordinary("git", ("status",), (), frozenset()))
        self.assertTrue(rs.ordinary("go", ("test",), (), frozenset()))
        self.assertFalse(rs.ordinary("go", ("test",), (), frozenset({"-overlay"})))
        self.assertFalse(rs.ordinary("gh", ("api", "graphql"), (), frozenset()))


class Report(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report, cls.notes = run()

    def test_command_shapes_merge_variants_and_drop_ordinary_use(self):
        g = group(self.report, "command shapes", "go test -overlay")
        self.assertEqual((g["sessions"], g["calls"]), (3, 3))
        self.assertEqual(g["examples"], FIXTURE_SESSIONS)
        self.assertLessEqual(len(g["sample"]), 160)
        shapes = {r["shape"] for r in self.report["command shapes"]}
        self.assertEqual(shapes, {"go test -overlay", "frobctl sync --target", "mutate.py"})
        every, _ = rs.analyze(source(), rs.parse_since("2026-09-01"), min_sessions=1, top=50)
        words = {r["shape"].split()[0] for r in every["command shapes"]}
        self.assertEqual(words, {"go", "frobctl", "mutate.py", "shots.mjs"})

    def test_scripts_group_across_renamed_files_and_variables(self):
        rows = [r for r in self.report["agent-written scripts"] if ".screenshot()" in r["shape"]]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sessions"], 3)
        self.assertTrue(rows[0]["shape"].startswith("[js]"))

    def test_repeated_helper_definitions(self):
        g = group(self.report, "repeated helpers", "[js] call")
        self.assertEqual((g["sessions"], g["calls"]), (3, 3))
        self.assertIn('tools.call("gw_call"', g["sample"])

    def test_failed_then_retried(self):
        g = group(self.report, "failed then retried", "bash: frobctl sync --target")
        self.assertEqual(g["sessions"], 3)

    def test_existing_tool_flag(self):
        self.assertEqual(group(self.report, "command shapes", "mutate.py")["existing"], ["mutate.py"])
        self.assertEqual(group(self.report, "command shapes", "go test -overlay")["existing"], [])

    def test_malformed_line_is_skipped_and_reported(self):
        self.assertEqual(self.report["stats"]["calls"], 22)
        self.assertTrue(any("2026-10-02_s2.jsonl: skipped 1 malformed" in n for n in self.notes))

    def test_since_filter(self):
        old, _ = run(since="2019-01-01")
        self.assertEqual(group(old, "command shapes", "go test -overlay")["sessions"], 4)
        none, _ = run(since="2027-01-01")
        self.assertEqual(none["stats"]["sessions"], 0)
        self.assertEqual(rs.parse_since("2026-10-02"), datetime(2026, 10, 2, tzinfo=timezone.utc))

    def test_existing_tool_dirs_from_env(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "frobctl"), "w").close()
            rep, _ = run(tool_dirs=[d])
        self.assertEqual(group(rep, "command shapes", "frobctl sync --target")["existing"], ["frobctl"])
        self.assertEqual(group(self.report, "command shapes", "frobctl sync --target")["existing"], [])


class Cli(unittest.TestCase):
    def cli(self, *args, **env):
        e = dict(os.environ, HWORKS_PI_SESSIONS=FIXTURES, HWORKS_TASKS_DIR="/fake-tasks")
        e.update(env)
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=e, check=True)

    def test_json_rows(self):
        rows = [json.loads(line) for line in self.cli("--since", "2026-09-01", "--json").stdout.splitlines()]
        self.assertIn(("command shapes", "go test -overlay", 3), [(r["section"], r["shape"], r["sessions"]) for r in rows])

    def test_min_sessions_and_top(self):
        out = self.cli("--since", "2026-09-01", "--json", "--min-sessions", "4").stdout
        self.assertEqual(out, "")
        rows = self.cli("--since", "2026-09-01", "--json", "--top", "1").stdout.splitlines()
        self.assertEqual(len([r for r in rows if '"command shapes"' in r]), 1)

    def test_missing_source_is_reported_not_fatal(self):
        p = self.cli("--since", "7d", HWORKS_PI_SESSIONS="/nonexistent/sessions")
        self.assertIn("pi sessions: not found (/nonexistent/sessions)", p.stderr)

    def test_help_comes_from_the_header(self):
        self.assertIn("usage: retro-sessions.py [--since YYYY-MM-DD|7d]", self.cli("--help").stdout)


if __name__ == "__main__":
    unittest.main()
