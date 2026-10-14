import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "operator-signals.py")
FIXTURES = os.path.join(HERE, "testdata", "operator-signals")

spec = importlib.util.spec_from_file_location("operator_signals", SCRIPT)
os_ = importlib.util.module_from_spec(spec)
spec.loader.exec_module(os_)

SKIP = re.compile("^AUTOPING")


def run(since="2026-09-01", skip=SKIP, prefix=None, **kw):
    src = {"sessions": FIXTURES, "skip": skip, "prefix": prefix}
    kw.setdefault("min_sessions", 1)
    report, _ = os_.analyze(src, os_.parse_since(since), **kw)
    return report


def keys(report, signal):
    return {g["key"]: (g["sessions"], g["count"]) for g in report[signal]["groups"]}


def texts(report, signal):
    return [e["text"] for g in report[signal]["groups"] for e in g["examples"]]


def op(text, prev_stop="stop"):
    return {"text": text, "skills": [], "ts": "", "agent": "", "prev_stop": prev_stop}


class Scope(unittest.TestCase):
    def test_subagent_and_out_of_window_sessions_are_skipped(self):
        r = run()
        t = r["totals"]
        self.assertEqual((t["sessions"], t["skipped_subagent"], t["skipped_out_of_window"]), (3, 2, 1))
        sessions = {e["session"] for sec in ("approval", "correction", "repeat") for g in r[sec]["groups"]
                    for e in g["examples"]}
        self.assertFalse(any("run-0" in s or "subagent-artifacts" in s or "old" in s for s in sessions), sessions)

    def test_subagent_path_patterns(self):
        for p in ("/s/x/run-12/session.jsonl", "/s/x/abc_reviewer_transcript.jsonl", "/s/x/subagent-artifacts/a.jsonl"):
            self.assertTrue(os_.SUBAGENT.search(p), p)
        for p in ("/s/x/session.jsonl", "/s/run-dir/2026_s.jsonl"):
            self.assertFalse(os_.SUBAGENT.search(p), p)

    def test_operator_skip_drops_messages_and_sessions(self):
        with_skip, without = run(), run(skip=None)
        self.assertEqual(with_skip["totals"]["skipped_no_operator_text"], 1)
        self.assertEqual(without["totals"]["sessions"], 4)
        self.assertEqual(without["totals"]["operator_messages"] - with_skip["totals"]["operator_messages"], 2)

    def test_cwd_match_keeps_matching_sessions(self):
        r = run(cwd_match=["/w/b"])
        self.assertEqual((r["totals"]["sessions"], r["totals"]["skipped_cwd"]), (1, 3))

    def test_missing_source_is_reported(self):
        report, _ = os_.analyze({"sessions": "/nonexistent/s", "skip": None, "prefix": None},
                                os_.parse_since("7d"))
        self.assertEqual(report["totals"]["sessions"], 0)
        self.assertIn("pi sessions: not found (/nonexistent/s)", report["missing"])


class Injections(unittest.TestCase):
    def test_skill_block_is_stripped_and_counted(self):
        text, skills = os_.strip_injections('<skill name="retro" location="/x">\nbody\n</skill>\n\nrun it now')
        self.assertEqual((text, skills), ("run it now", ["retro"]))
        r = run()
        self.assertEqual(r["skills"]["skills"], [{"name": "review-loop", "sessions": 1, "count": 1}])
        self.assertEqual(r["skills"]["sessions_without_skill"], 2)

    def test_other_leading_tag_blocks_are_stripped(self):
        self.assertEqual(os_.strip_injections('<note a="1">x</note>\n<b>y</b> keep <i>this</i>'),
                         ("keep <i>this</i>", []))
        repeat = texts(run(), "repeat")
        self.assertTrue(all(t.startswith("Please refactor") for t in repeat), repeat)

    def test_injected_prefix_env_strips_more(self):
        self.assertEqual(os_.strip_injections("[auto: x] do the thing", re.compile(r"\[auto:[^\]]*\]")),
                         ("do the thing", []))

    def test_cli_reads_skip_and_prefix_from_env(self):
        out = subprocess.run([sys.executable, SCRIPT, "--since", "2026-09-01", "--json"], capture_output=True,
                             text=True, check=True,
                             env=dict(os.environ, HWORKS_PI_SESSIONS=FIXTURES, HWORKS_OPERATOR_SKIP="^AUTOPING",
                                      HWORKS_INJECTED_PREFIX=r"Please refactor the parser module so that it handles"))
        r = json.loads(out.stdout)
        self.assertEqual(r["totals"]["skipped_no_operator_text"], 1)
        self.assertEqual(r["repeat"]["groups"], [])


class Signals(unittest.TestCase):
    def test_approval_after_ended_turn(self):
        self.assertEqual(keys(run(), "approval"), {"yes": (2, 2)})
        for t in ("ok", "go ahead", "LGTM.", "ship it", "Sounds good!"):
            self.assertTrue(os_.approval(op(t)), t)

    def test_approval_near_misses(self):
        self.assertIsNone(os_.approval(op("yes, but first check that the migration handles the empty table")))
        self.assertIsNone(os_.approval(op("ok", prev_stop="toolUse")))
        self.assertIsNone(os_.approval(op("no tests fail now, ship it")))
        self.assertNotIn("ok", texts(run(), "approval"))

    def test_status_check(self):
        self.assertEqual(keys(run(), "status-check"), {"status": (1, 1), "checking progress": (1, 1)})
        self.assertIsNone(os_.status_check(op(
            "What is the status of the deploy pipeline and the rollback plan for tomorrow morning?")))
        for text in ("status?", "update?", "Any update?", "checking progress", "how's it going?",
                     "what's the status", "where are we at", "progress check please"):
            self.assertTrue(os_.status_check(op(text)), text)
        for text in ("Add a progress bar", "Show git status", "The status is green", "update the README",
                     "fix the eta display"):
            self.assertIsNone(os_.status_check(op(text)), text)

    def test_correction(self):
        self.assertEqual(keys(run(), "correction"), {"actually": (2, 2), "no": (1, 1)})
        for t in ("no", "No.", "no, the other one", "no that is wrong", "I meant the other file", "revert that"):
            self.assertTrue(os_.correction(op(t)), t)

    def test_correction_near_misses(self):
        for t in ("no tests fail now, ship it", "now run it", "nothing else", "notably faster", "add an undo button"):
            self.assertIsNone(os_.correction(op(t)), t)

    def test_abort_keys_on_stop_reason(self):
        self.assertEqual(keys(run(), "abort"), {"after an aborted turn": (2, 2)})
        self.assertTrue(os_.abort(op("keep going", prev_stop="aborted")))
        self.assertIsNone(os_.abort(op("Actually, run only the parser tests", prev_stop="stop")))

    def test_repeat_groups_across_sessions_not_within_one(self):
        groups = run()["repeat"]["groups"]
        self.assertEqual([(g["sessions"], g["count"]) for g in groups], [(2, 2)])
        self.assertEqual({e["session"] for e in groups[0]["examples"]},
                         {"proj-a/2026-10-01_s1.jsonl", "proj-b/2026-10-02_s2.jsonl"})

    def test_repeat_survives_heavy_repetition(self):
        same = os_.shingles("please rebase this branch on main, rerun the full gate, and report each failure")
        other = os_.shingles("something unrelated entirely about writing the release notes for the week")
        groups = os_.cluster([same] * 201 + [other], os_.REPEAT_THRESHOLD)
        self.assertIn(list(range(201)), groups)
        self.assertIn([201], groups)

    def test_repeat_survives_heavy_near_duplicates(self):
        sets = [os_.shingles(f"please rebase this branch on main, rerun the full gate, and report each failure for ticket{n}")
                for n in range(201)]
        self.assertEqual(os_.cluster(sets, os_.REPEAT_THRESHOLD), [list(range(201))])

    def test_repeat_survives_interleaved_template_distractors(self):
        base = "please rebase this branch on main, rerun the full gate, and report each failure"
        words = [f"w{n}" for n in range(201 * 30)]
        distractors = [os_.shingles(base + " " + " ".join(words[k * 30:(k + 1) * 30])) for k in range(201)]
        a, b = os_.shingles(base + " for ticket0"), os_.shingles(base + " for ticket1")
        groups = os_.cluster([a] + distractors + [b], os_.REPEAT_THRESHOLD)
        self.assertIn([0, 202], groups)

    def test_size_bound_keeps_exact_threshold_match(self):
        small = frozenset(f"s{n}" for n in range(14))
        big = small | frozenset(f"t{n}" for n in range(11))
        self.assertEqual(os_.jaccard(small, big), 0.56)
        self.assertEqual(os_.cluster([small, big], 0.56), [[0, 1]])

    def test_repeat_threshold(self):
        a = os_.shingles("one two three four five six seven eight nine ten")
        b = os_.shingles("one two three four five six seven eight nine eleven")
        c = os_.shingles("ten nine eight seven six five four three two one")
        self.assertGreaterEqual(os_.jaccard(a, b), os_.REPEAT_THRESHOLD)
        self.assertLess(os_.jaccard(a, c), os_.REPEAT_THRESHOLD)

    def test_min_sessions_hides_groups_but_not_skills_or_shape(self):
        r = run(min_sessions=2)
        self.assertEqual(keys(r, "correction"), {"actually": (2, 2)})
        self.assertEqual(keys(r, "status-check"), {})
        self.assertEqual(r["status-check"]["count"], 2)
        self.assertEqual(len(r["skills"]["skills"]), 1)
        self.assertEqual(len(r["repeat"]["groups"]), 1)
        self.assertEqual(run(min_sessions=3)["repeat"]["groups"], [])

    def test_prompt_shape(self):
        shape = {b["bucket"]: b for b in run()["prompt-shape"]}
        self.assertEqual([b for b in shape], ["terse", "short", "medium", "long"])
        self.assertEqual((shape["short"]["sessions"], shape["short"]["median_messages"],
                          shape["short"]["flagged_share"]), (3, 5, 1.0))
        self.assertEqual(shape["terse"]["sessions"], 0)
        self.assertEqual([os_.bucket(n) for n in (0, 10, 11, 40, 41, 150, 151)],
                         ["terse", "terse", "short", "short", "medium", "medium", "long"])

    def test_examples_and_max_chars(self):
        r = run(examples=1, max_chars=20)
        ex = r["approval"]["groups"][0]["examples"]
        self.assertEqual(len(ex), 1)
        self.assertEqual(ex[0]["agent"], "The refactor is r...")
        self.assertEqual(ex[0]["timestamp"], "2026-10-01T10:03:00Z")


class Cli(unittest.TestCase):
    def cli(self, *args):
        env = dict(os.environ, HWORKS_PI_SESSIONS=FIXTURES, HWORKS_OPERATOR_SKIP="^AUTOPING")
        env.pop("HWORKS_INJECTED_PREFIX", None)
        return subprocess.run([sys.executable, SCRIPT, "--since", "2026-09-01", *args], capture_output=True,
                              text=True, env=env, check=True)

    def test_json_round_trips(self):
        r = json.loads(self.cli("--json", "--min-sessions", "1").stdout)
        self.assertEqual(r, json.loads(json.dumps(run())))

    def test_text_report_has_header_and_sections(self):
        out = self.cli().stdout
        self.assertIn("3 sessions, 15 operator messages", out)
        self.assertIn("2 subagent, 1 out of window, 1 no operator text", out)
        for sec in ("approval", "status-check", "correction", "abort", "repeat", "skills", "prompt-shape"):
            self.assertIn(f"== {sec} ==", out)
        self.assertIn("review-loop", out)


if __name__ == "__main__":
    unittest.main()
