import json
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "blockers.sh")

ALPHA_FRICTION = """# friction

- 2026-10-02 [missed-defect] approve not reset after a reverted router call | reviewer | 1 review round | an invariant test template
- 2026-10-03 [wrong-assumption] assumed USDC has 18 decimals | Operator | reran fork tests | token metadata in the brief
- 2020-01-01 [toolchain] stale entry | ci | - | -
- [test-gap] undated line | test
- a note that is not an entry
"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class Friction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tasks = self.tmp.name
        write(os.path.join(self.tasks, "github.com--o--alpha", "main", "t1", "friction.md"), ALPHA_FRICTION)
        write(os.path.join(self.tasks, "github.com--o--alpha", "main", "t1", "open-questions.md"),
              "- [tooling] which fork block | latest | none | pin one\n")
        write(os.path.join(self.tasks, "github.com--o--beta", "dev", "t2", "friction.md"),
              "- 2026-10-04 [env] RPC rate limit | self | 3 retries | a local node\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        missing = os.path.join(self.tasks, "missing")
        env = dict(os.environ, HWORKS_TASKS_DIR=self.tasks, HWORKS_BLOCKERS_LOG=missing, HWORKS_SUBAGENT_RUNS=missing,
                   HWORKS_RUN_HISTORY=missing, HWORKS_HARNESS_AUDIT_LOG=missing)
        return subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True, env=env, check=True)

    def rows(self, *args):
        return [json.loads(line) for line in self.run_script("--since", "2026-01-01", "--json", *args).stdout.splitlines()]

    def test_json_reports_missing_sources_on_stderr(self):
        result = self.run_script('--since', '2026-01-01', '--json')
        self.assertIn('note: subagent runs: not found', result.stderr)
        self.assertEqual({r['source'] for r in map(json.loads, result.stdout.splitlines())}, {'friction', 'open-questions'})

    def test_entries_group_by_who_caught_them_and_category(self):
        got = {(r["kind"], r["rule"], r["ts"][:10]) for r in self.rows() if r["source"] == "friction"}
        undated = [r for r in self.rows() if r["rule"] == "test-gap"]
        self.assertEqual(len(undated), 1)
        self.assertEqual(got, {("reviewer", "missed-defect", "2026-10-02"), ("operator", "wrong-assumption", "2026-10-03"),
                               ("self", "env", "2026-10-04"), ("test", "test-gap", undated[0]["ts"][:10])})

    def test_entry_date_wins_over_file_mtime_for_since(self):
        stale = [r for r in self.rows() if r["rule"] == "toolchain"]
        self.assertEqual(stale, [])
        old = self.run_script("--since", "2019-01-01", "--json").stdout
        self.assertIn('"toolchain"', old)

    def test_missing_caught_by_is_unknown(self):
        write(os.path.join(self.tasks, "x", "friction.md"), "- 2026-10-05 [rework] redid the encoder\n")
        self.assertIn(("unknown", "rework"), {(r["kind"], r["rule"]) for r in self.rows()})

    def test_cwd_match_scopes_every_task_source(self):
        alpha = self.rows("--cwd-match", "ALPHA")
        self.assertEqual({r["cwd"].split("/")[0] for r in alpha}, {"github.com--o--alpha"})
        self.assertEqual({r["source"] for r in alpha}, {"friction", "open-questions"})
        both = self.rows("--cwd-match", "--o--alpha", "--cwd-match", "--o--beta")
        self.assertEqual(len(both), len(self.rows()))
        self.assertEqual(self.rows("--cwd-match", "gamma"), [])

    def test_source_and_kind_filter_events(self):
        got = self.rows("--source", "friction", "--kind", "operator")
        self.assertEqual([(r["source"], r["kind"], r["rule"]) for r in got], [("friction", "operator", "wrong-assumption")])
        self.assertEqual({r["source"] for r in self.rows("--source", "open-questions")}, {"open-questions"})

    def test_state_field_sets_stage_and_verdict(self):
        write(os.path.join(self.tasks, "github.com--o--alpha", "main", "t3", "open-questions.md"),
              "- [permission] push to main? | no | user grant missing | push later | deferred\n"
              "- [permission] delete branch? | keep | unmerged | delete later | deferred:reversed\n"
              "- [ambiguous-brief] scope the API? | v1 only | spec says v1 | widen later | asked:kept\n"
              "- [tooling] which runner | pytest | repo uses it | switch | deferred:Kept\n"
              "- [tooling] bad state | x | y | z | later\n")
        got = sorted((r["kind"], r["rule"], r["verdict"]) for r in self.rows() if r["cwd"].endswith("t3"))
        self.assertEqual(got, [("asked", "ambiguous-brief", "kept"), ("deferred", "permission", "open"),
                               ("deferred", "permission", "reversed"), ("deferred", "tooling", "kept"),
                               ("unrecorded", "tooling", None)])

    def test_legacy_entry_without_state_is_unrecorded(self):
        legacy = [r for r in self.rows() if r["source"] == "open-questions" and r["cwd"].endswith("t1")]
        self.assertEqual([(r["kind"], r["verdict"]) for r in legacy], [("unrecorded", None)])

    def test_text_report_counts_outcomes(self):
        write(os.path.join(self.tasks, "github.com--o--alpha", "main", "t3", "open-questions.md"),
              "- [permission] a | b | c | d | deferred:reversed\n- [permission] e | f | g | h | deferred:kept\n"
              "- [permission] i | j | k | l | deferred\n")
        out = self.run_script("--since", "2026-01-01").stdout
        self.assertIn("Decision outcomes", out)
        self.assertRegex(out, r"deferred\s+\(all\)\s+1\s+1\s+1\s+1/2 \(50%\)")
        self.assertRegex(out, r"deferred\s+permission\s+1\s+1\s+1\s+1/2 \(50%\)")
        self.assertIn("1 open-question entries have no state field", out)

    def test_text_report_names_the_class(self):
        out = self.run_script("--since", "2026-01-01").stdout
        self.assertIn("friction / reviewer / missed-defect", out)

    def test_log_prints_decisions_and_corrections_by_task_over_all_history(self):
        write(os.path.join(self.tasks, "github.com--o--alpha", "main", "t1", ".task"),
              "created=2026-09-30T10:00:00Z\nrepo=github.com--o--alpha\nbranch=Hughy/Main\nslug=t1\n")
        write(os.path.join(self.tasks, "github.com--o--alpha", "main", "t1", "open-questions.md"),
              "- [ambiguous-brief] split the router? | one module | router.go:12 has one caller | split later | deferred:reversed\n")
        out = self.run_script("--log", "--cwd-match", "alpha").stdout
        self.assertIn("## github.com--o--alpha @ Hughy/Main: t1\n", out)
        self.assertIn("created 2026-09-30", out)
        self.assertIn("- [ambiguous-brief] split the router? (deferred:reversed)\n    chose: one module\n"
                      "    evidence: router.go:12 has one caller\n    reverse: split later\n", out)
        self.assertIn("- correction [missed-defect] approve not reset after a reverted router call (caught by reviewer, "
                      "2026-10-02)\n    cost: 1 review round\n    would have helped: an invariant test template\n", out)
        self.assertIn("- correction [toolchain] stale entry (caught by ci, 2020-01-01)", out)
        self.assertNotIn("beta", out)

    def test_grep_matches_full_entry_text(self):
        write(os.path.join(self.tasks, "github.com--o--beta", "dev", "t2", "open-questions.md"),
              f"- [tooling] where does pricing live | quote pkg | {'x' * 250} internal/quote/price.go | move it | deferred\n")
        got = self.rows("--grep", "INTERNAL/QUOTE", "--grep", "rate limit")
        self.assertEqual(sorted((r["source"], r["rule"]) for r in got), [("friction", "env"), ("open-questions", "tooling")])
        self.assertEqual(got[0]["cwd"], got[1]["cwd"])
        self.assertEqual([r["rule"] for r in self.rows("--grep", "[wrong-assumption]")], ["wrong-assumption"])


if __name__ == "__main__":
    unittest.main()
