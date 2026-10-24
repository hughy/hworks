import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "kaizen-sessions.py")
FIXTURES = os.path.join(HERE, "testdata", "kaizen-sessions")
FIXTURE_SESSIONS = ["proj-a/2026-10-01_s1.jsonl", "proj-a/2026-10-02_s2.jsonl", "proj-b/2026-10-03_s3.jsonl"]

spec = importlib.util.spec_from_file_location("kaizen_sessions", SCRIPT)
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

    def test_interpreter_heredoc_becomes_an_inline_script(self):
        for cmd, lang in (("python3 <<'EOF'", "py"), ("python3 - <<EOF", "py"), ("cd /w && node <<-\"EOF\"", "js"),
                          ("bash << EOF", "sh")):
            call = {"name": "bash", "args": {"command": cmd + "\nimport os\nprint(1)\nEOF"}}
            self.assertEqual([(s["kind"], s["lang"], s["code"]) for s in rs.call_scripts(call, source())],
                             [("inline", lang, "import os\nprint(1)")], cmd)

    def test_heredoc_is_data_when_interpreter_has_code_or_script_file(self):
        for cmd in ("python3 -c 'import json,sys; print(json.load(sys.stdin))' <<'EOF'", "python3 scripts/reader.py <<'EOF'",
                    "node -e 'process.stdin.pipe(process.stdout)' <<EOF", "python3 -uc 'print(1)' <<EOF",
                    "bash -c 'cat' <<EOF", "node --eval 'x' <<EOF", "python3 -m json.tool <<EOF"):
            call = {"name": "bash", "args": {"command": cmd + "\n{\n  \"enabled\": true\n}\nEOF"}}
            codes = [s["code"] for s in rs.call_scripts(call, source())]
            self.assertNotIn('{\n  "enabled": true\n}', codes, cmd)
        for cmd in ("bash -e <<EOF", "bash -s arg <<EOF", "python3 -u - <<EOF", "node --input-type=module <<EOF"):
            call = {"name": "bash", "args": {"command": cmd + "\nimport os\nEOF"}}
            self.assertEqual([s["code"] for s in rs.call_scripts(call, source())], ["import os"], cmd)

    def test_tee_heredoc_writes_a_script_file(self):
        for cmd in ("tee /tmp/a.py <<'EOF'", "tee -a /tmp/a.py <<'EOF'", "cat <<'EOF' | tee /tmp/a.py >/dev/null"):
            call = {"name": "bash", "args": {"command": cmd + "\nimport os\nx = 1\nprint(x)\nEOF"}}
            self.assertEqual([(s["path"], s["lang"]) for s in rs.call_scripts(call, source())],
                             [("/tmp/a.py", "py")], cmd)

    def test_shebang_language(self):
        for line, lang in (("#!/usr/bin/env python3", "py"), ("#!/usr/bin/python3.11", "py"), ("#!/bin/bash", "sh"),
                           ("#!/usr/bin/env node", "js"), ("#!/usr/bin/env -S node --no-warnings", "js")):
            self.assertEqual(rs.shebang_lang(line + "\nx\n"), lang, line)
        self.assertIsNone(rs.shebang_lang("#!/usr/bin/env frob\n"))
        self.assertIsNone(rs.shebang_lang("print(1)\n"))

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

    def test_scripts_count_worktree_files_and_label_location(self):
        rows = [r for r in self.report["agent-written scripts"] if ".screenshot()" in r["shape"]]
        self.assertEqual(rows[0]["where"], {"scratch": 2, "worktree": 1})
        g = group(self.report, "agent-written scripts", "[js] .call(), call(\"gw_call\"), def call")
        self.assertEqual(g["where"], {"inline": 3})

    def test_worktree_scripts_committed_later_are_kept(self):
        g = [r for r in self.report["agent-written scripts"] if r["shape"].startswith("[py]")]
        self.assertEqual((g[0]["sessions"], g[0]["where"]), (3, {"worktree": 3}))
        self.assertEqual(self.report["stats"]["scripts"], 9)

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
        self.assertEqual(self.report["stats"]["calls"], 28)
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


def write_sessions(d, n, calls, cwd="/w", prefix="s"):
    """n transcripts in d, each holding calls: (tool name, arguments, errored)."""
    for k in range(n):
        lines = [{"type": "session", "id": str(k), "timestamp": "2026-10-01T10:00:00.000Z", "cwd": cwd}]
        for i, (name, args, err) in enumerate(calls):
            ts = "2026-10-01T10:%02d:00.000Z" % i
            lines.append({"type": "message", "timestamp": ts, "message": {"role": "assistant", "content": [
                {"type": "toolCall", "id": f"c{i}", "name": name, "arguments": args}]}})
            lines.append({"type": "message", "timestamp": ts, "message": {
                "role": "toolResult", "toolCallId": f"c{i}", "isError": err, "content": []}})
        with open(os.path.join(d, f"{prefix}{k:02d}.jsonl"), "w") as f:
            f.write("\n".join(json.dumps(x) for x in lines) + "\n")


HELPER = "#!/usr/bin/env python3\nimport sys\ndef unpack(data):\n    return data.strip()\nprint(unpack(sys.argv[1]))\n"


class Synthetic(unittest.TestCase):
    def analyze(self, n, calls):
        with tempfile.TemporaryDirectory() as d:
            write_sessions(d, n, calls)
            rep, _ = rs.analyze(source(sessions=d), rs.parse_since("2026-09-01"), min_sessions=3, top=15)
        return rep

    def test_retry_found_after_unrelated_calls(self):
        sync = ("bash", {"command": "frobctl sync --target a"}, False)
        reads = [("read", {"path": f"/w/f{i}"}, False) for i in range(4)]
        rep = self.analyze(3, [(sync[0], sync[1], True)] + reads + [sync])
        self.assertEqual(group(rep, "failed then retried", "bash: frobctl sync --target")["sessions"], 3)

    def test_cwd_match_keeps_only_matching_sessions(self):
        sync = [("bash", {"command": "frobctl sync --target a"}, False)]
        with tempfile.TemporaryDirectory() as d:
            write_sessions(d, 3, sync, cwd="/home/u/worktrees/Policy-Demo-review/x", prefix="a")
            write_sessions(d, 2, sync, cwd="/home/u/dev/other", prefix="b")
            src, since = source(sessions=d), rs.parse_since("2026-09-01")
            everything, _ = rs.analyze(src, since, min_sessions=1)
            scoped, _ = rs.analyze(src, since, min_sessions=1, cwd_match=["policy-demo"])
            either, _ = rs.analyze(src, since, min_sessions=1, cwd_match=["policy-demo", "/other"])
            none, _ = rs.analyze(src, since, min_sessions=1, cwd_match=["absent"])
        self.assertEqual([r["stats"]["sessions"] for r in (everything, scoped, either, none)], [5, 3, 5, 0])
        self.assertEqual(group(scoped, "command shapes", "frobctl sync --target")["examples"],
                         ["a00.jsonl", "a01.jsonl", "a02.jsonl"])

    def test_extensionless_shebang_file_counts(self):
        rep = self.analyze(3, [("write", {"path": "/w/a/bin/helper", "content": HELPER}, False)])
        self.assertEqual(rep["stats"]["scripts"], 3)

    def test_relative_path_is_labelled_against_the_session_cwd_without_cd_tracking(self):
        call = {"name": "bash", "args": {"command": "cd /tmp && cat > a.py <<'X'\nx\nX\ntee /tmp/b.py <<'Y'\ny\nY"}}
        self.assertEqual([(s["path"], s["where"]) for s in rs.call_scripts(call, source(), "/w")],
                         [("/w/a.py", "worktree"), ("/tmp/b.py", "scratch")])
        write = {"name": "write", "args": {"path": "notes/c.py", "content": "x"}}
        self.assertEqual([(s["path"], s["where"]) for s in rs.call_scripts(write, source(), "/tmp/t")],
                         [("/tmp/t/notes/c.py", "scratch")])

    def test_committed_script_is_never_dropped(self):
        write = ("write", {"path": "/w/helper.py", "content": HELPER}, False)
        rep = self.analyze(3, [write, ("bash", {"command": "cd /w && git add helper.py && git commit -m x"}, False)])
        self.assertEqual(rep["stats"]["scripts"], 3)

    def test_helper_reported_however_many_sessions_repeat_it(self):
        code = "function unpack(data) { return JSON.parse(data); }\nconst r = unpack(x);\nconsole.log(r);\n"
        for n in (3, 30):
            rep = self.analyze(n, [("mcpScript", {"code": code}, False)])
            self.assertEqual(group(rep, "repeated helpers", "[js] unpack")["sessions"], n, n)


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

    def test_cwd_match_flag(self):
        rows = self.cli("--since", "2026-09-01", "--json", "--min-sessions", "1", "--cwd-match", "/nowhere").stdout
        self.assertEqual(rows, "")
        rows = self.cli("--since", "2026-09-01", "--json", "--cwd-match", "/W").stdout
        self.assertIn('"go test -overlay"', rows)

    def test_missing_source_is_reported_not_fatal(self):
        p = self.cli("--since", "7d", HWORKS_PI_SESSIONS="/nonexistent/sessions")
        self.assertIn("pi sessions: not found (/nonexistent/sessions)", p.stderr)

    def test_help_comes_from_the_header(self):
        self.assertIn("usage: kaizen-sessions.py [--since YYYY-MM-DD|7d]", self.cli("--help").stdout)


def linked_worktree(tmp):
    """A main checkout with adapters/local and a linked worktree of it without one."""
    main, wt = os.path.join(tmp, "main"), os.path.join(tmp, "wt")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    for args in (["init", "-q", main], ["-C", main, "commit", "-q", "--allow-empty", "-m", "x"],
                 ["-C", main, "worktree", "add", "-q", wt]):
        subprocess.run(git + args, env=env, check=True, capture_output=True)
    os.makedirs(os.path.join(main, "adapters", "local"))
    return main, wt


class LocalEnv(unittest.TestCase):
    def test_linked_worktree_reads_main_checkout_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            main, wt = linked_worktree(tmp)
            with open(os.path.join(main, "adapters", "local", "x.env"), "w") as f:
                f.write("HWORKS_TEST_LOCAL_ENV=from-main\n")
            self.addCleanup(os.environ.pop, "HWORKS_TEST_LOCAL_ENV", None)
            rs.load_env_files(wt)
            self.assertEqual(os.environ.get("HWORKS_TEST_LOCAL_ENV"), "from-main")


if __name__ == "__main__":
    unittest.main()
