import contextlib
import fcntl
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "orchestrate.py")
FIXTURES = os.path.join(HERE, "testdata", "orchestrate")
FAKE_ARGS_SCRIPT = os.path.join(HERE, "testdata", "fake-review-loop-args.sh")
sys.path.insert(0, HERE)
import orchestrate  # noqa: E402


def sh(cwd, *args):
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(args), cwd=cwd,
                       capture_output=True, text=True, check=True)
    return p.stdout.strip()


class OrchestrateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = os.path.realpath(tempfile.mkdtemp(prefix="orchestrate-template-"))
        cls.addClassCleanup(shutil.rmtree, cls.template)
        repo = os.path.join(cls.template, "repo")
        os.makedirs(repo)
        sh(repo, "init", "-q", "-b", "main")
        with open(os.path.join(repo, "README"), "w") as f:
            f.write("seed\n")
        sh(repo, "add", "README")
        sh(repo, "commit", "-q", "-m", "seed")

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="orchestrate-test-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = os.path.join(self.tmp, "repo")
        shutil.copytree(os.path.join(self.template, "repo"), self.repo, symlinks=True)
        self.store = os.path.join(self.tmp, "store")
        self.runs = os.path.join(self.tmp, "runs")
        os.makedirs(self.runs)
        self.env = dict(os.environ, PI_SETTINGS=os.path.join(self.tmp, "no-settings.json"),
                        ORCHESTRATE_ARGS_SCRIPT=FAKE_ARGS_SCRIPT)
        self.env.pop("PI_PROVIDER", None)
        self.env.pop("PI_MODEL", None)
        self.env.pop("PI_SESSION_ID", None)
        self.seq = 0

    # ---------- helpers ----------

    def g(self, *args, code=0):
        """Run orchestrate.main in this process, with self.env as the environment its children inherit."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            try:
                rc = orchestrate.main(["--store", self.store] + list(args))
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        self.assertEqual(rc, code, "orchestrate %s\nstdout: %s\nstderr: %s" % (args, out.getvalue(), err.getvalue()))
        return out.getvalue()

    def cli(self, *args, timeout=60):
        """Run orchestrate.py as a separate process."""
        return subprocess.run([sys.executable, SCRIPT, "--store", self.store] + list(args), capture_output=True,
                              text=True, env=self.env, timeout=timeout)

    def init(self, *extra):
        self.g("init", "--repo", self.repo, "--base", "main", "--worktrees", os.path.join(self.tmp, "wt"),
               "--gate", "true", *extra)

    def load(self, units):
        path = os.path.join(self.tmp, "units-%d.json" % self.seq)
        self.seq += 1
        with open(path, "w") as f:
            json.dump(units, f)
        return self.g("import", path)

    def rows(self):
        return {r["id"]: r for r in orchestrate.read_rows(self.store)}

    def next(self, n=3):
        return json.loads(self.g("next", "--max", str(n), "--json"))["selected"]

    def launch(self, uid, *extra, code=0):
        out = self.g("launch", uid, *extra, code=code)
        return json.loads(out) if out.strip() else None

    def wt(self, uid):
        return os.path.join(self.tmp, "wt", uid)

    def commit(self, uid, name="work.txt"):
        with open(os.path.join(self.wt(uid), name), "a") as f:
            f.write("change\n")
        sh(self.wt(uid), "add", name)
        sh(self.wt(uid), "commit", "-q", "-m", "work")
        return sh(self.wt(uid), "rev-parse", "HEAD")

    def fixture(self, name, run, edit=None):
        """Copy a captured run dir into runs/<run>, renamed to run, with edit applied to status.json."""
        src = os.path.join(FIXTURES, name)
        dst = os.path.join(self.runs, run)
        os.makedirs(dst)
        for fn in os.listdir(src):
            with open(os.path.join(src, fn)) as f:
                doc = json.load(f)
            if fn == "status.json":
                doc["runId"] = run
                if edit:
                    edit(doc)
            else:
                doc["workflowRunId"] = run
            with open(os.path.join(dst, fn), "w") as f:
                json.dump(doc, f)
        return os.path.join(dst, "status.json")

    def workflow(self, name, run, head, value_edit=None):
        def edit(doc):
            doc["workflow"]["value"]["head"] = head
            if value_edit:
                value_edit(doc["workflow"]["value"])
        return self.fixture(name, run, edit)

    def stopped(self, run, child="child-1", edit=None):
        """The stopped fixture, with its one child reference renamed to child, or removed when child is None."""
        def rename(doc):
            for ref in doc["steps"] + doc["workflowChildren"]["children"]:
                ref["runId"] = child
            if child is None:
                doc["steps"], doc["workflowChildren"]["children"] = [], []
            if edit:
                edit(doc)
        return self.fixture("stopped", run, rename)

    def child(self, run, parent, uid, pid, state="running"):
        def edit(doc):
            doc.update(cwd=self.wt(uid), parentWorkflowRunId=parent, pid=pid, state=state)
        return self.fixture("stopped-child", run, edit)

    def dead_pid(self):
        p = subprocess.Popen(["true"])
        p.wait()
        return p.pid

    def started(self, uid, run="wf-1"):
        spec = self.launch(uid)
        self.g("bind", uid, str(spec["attempt"]), run)
        return spec

    # ---------- tests ----------

    def test_launch_emits_args_and_brief_with_separate_process_section(self):
        del self.env["ORCHESTRATE_ARGS_SCRIPT"]
        self.init()
        self.load([{"id": "A", "title": "Add a thing", "url": "https://example.test/A", "body": "Thing exists.",
                    "paths": ["src/*"]}])
        spec = self.launch("A")
        self.assertEqual(spec["attempt"], 1)
        self.assertEqual(spec["cwd"], self.repo)
        self.assertTrue(spec["workflow"].endswith("workflows/review-loop.js"))
        with open(spec["args_path"]) as f:
            args = json.load(f)
        self.assertEqual(args["label"], "A")
        self.assertEqual(args["cwd"], self.wt("A"))
        self.assertEqual(args["base"], sh(self.repo, "rev-parse", "main"))
        self.assertEqual(args["reviewers"], 1)
        self.assertEqual(args["gate"], "true")
        with open(args["brief"]) as f:
            brief = f.read()
        acceptance, process = brief.split("## Process")
        self.assertIn("Thing exists.", acceptance)
        self.assertIn("https://example.test/A", acceptance)
        self.assertNotIn("commit", acceptance.lower())
        self.assertIn("Commit on this branch", process)
        self.assertEqual(sh(self.wt("A"), "symbolic-ref", "--short", "HEAD"), "orchestrate/A")
        r = self.rows()["A"]
        self.assertEqual((r["state"], r["start_head"]), ("launching", sh(self.repo, "rev-parse", "main")))

    def test_crash_after_intent_before_bind_relaunches_same_args(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        spec = self.launch("A")
        with open(spec["args_path"], "rb") as f:
            before = f.read()
        out = json.loads(self.g("reconcile", "--runs-dir", self.runs, "--json"))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["action"], "relaunch-same-args", out[0])
        self.assertEqual(out[0]["args_path"], spec["args_path"])
        self.assertEqual(out[0]["workflow"], spec["workflow"])
        with open(spec["args_path"], "rb") as f:
            self.assertEqual(f.read(), before)
        self.launch("A", "--force-window", code=3)
        self.assertEqual(self.rows()["A"]["attempt"], 1)
        self.g("bind", "A", "1", "wf-1")
        self.assertEqual(self.rows()["A"]["state"], "running")

    def test_intent_with_commits_but_no_bound_run_holds(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.launch("A")
        self.commit("A")
        out = json.loads(self.g("reconcile", "--runs-dir", self.runs, "--json"))
        self.assertEqual(out[0]["action"], "hold", out[0])

    def test_bind_rejects_wrong_attempt_and_rebind_keeps_prior_runs(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.launch("A")
        self.g("bind", "A", "2", "wf-1", code=3)
        self.g("bind", "A", "1", "wf-1")
        self.g("bind", "A", "1", "wf-2")
        self.g("bind", "A", "1", "wf-2")
        self.assertEqual(self.rows()["A"]["run"], "wf-1,wf-2")

    def test_clean_record_is_accepted_and_duplicate_record_is_a_noop(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A")
        head = self.commit("A")
        status = self.workflow("clean", "wf-1", head)
        self.g("record", "A", "1", status)
        r = self.rows()["A"]
        self.assertEqual((r["state"], r["head"], r["reason"]), ("clean", head, ""))
        rpath = os.path.join(self.store, "receipts", "A-1.json")
        with open(rpath) as f:
            receipt = json.load(f)
        self.assertEqual(receipt["run"], "wf-1")
        self.assertEqual(receipt["reviewed_head"], head)
        self.assertEqual(receipt["start_head"], sh(self.repo, "rev-parse", "main"))
        self.assertEqual(receipt["base"], sh(self.repo, "rev-parse", "main"))
        self.assertEqual(receipt["workflow_state"], "clean")
        self.assertEqual(receipt["reviewers"], [{"key": "review-1-1", "ok": True,
                                                 "run": "4adf0004-fae8-4496-abb5-0b6605464125"}])
        self.assertEqual(receipt["gate"], "true")
        self.assertEqual(receipt["rounds"], 1)
        with open(rpath, "rb") as f:
            receipt_bytes = f.read()
        with open(os.path.join(self.store, "units.tsv"), "rb") as f:
            tsv = f.read()
        out = self.g("record", "A", "1", os.path.join(self.runs, "wf-1", "workflow-receipt.json"))
        self.assertIn("already recorded", out)
        with open(rpath, "rb") as f:
            self.assertEqual(f.read(), receipt_bytes)
        with open(os.path.join(self.store, "units.tsv"), "rb") as f:
            self.assertEqual(f.read(), tsv)

    def test_record_reads_value_through_workflow_receipt(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A")
        head = self.commit("A")
        self.workflow("unresolved", "wf-1", head)
        self.g("record", "A", "1", os.path.join(self.runs, "wf-1", "workflow-receipt.json"))
        r = self.rows()["A"]
        self.assertEqual(r["state"], "unresolved")
        self.assertIn("1 blocking findings after 3 rounds", r["reason"])

    def test_late_record_for_superseded_attempt_changes_nothing(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        head = self.commit("A")
        status1 = self.workflow("unresolved", "wf-1", head)
        self.g("record", "A", "1", status1)
        self.started("A", "wf-2")
        self.assertEqual(self.rows()["A"]["attempt"], 2)
        self.g("bind", "A", "2", "wf-3")
        superseded = self.workflow("clean", "wf-2", head)
        self.g("record", "A", "2", self.workflow("unresolved", "wf-3", head))
        with open(os.path.join(self.store, "units.tsv"), "rb") as f:
            tsv = f.read()
        self.g("record", "A", "2", superseded, code=3)
        late = self.workflow("clean", "wf-late", head)
        self.g("record", "A", "1", status1, code=3)
        self.g("record", "A", "1", late, code=3)
        self.g("record", "A", "2", late, code=3)
        with open(os.path.join(self.store, "units.tsv"), "rb") as f:
            self.assertEqual(f.read(), tsv)
        with open(os.path.join(self.store, "receipts", "A-2.json")) as f:
            self.assertEqual(json.load(f)["run"], "wf-3")

    def test_clean_with_moved_head_is_stale(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A")
        head = self.commit("A")
        self.commit("A", "later.txt")
        self.g("record", "A", "1", self.workflow("clean", "wf-1", head))
        r = self.rows()["A"]
        self.assertEqual(r["state"], "stale")
        self.assertIn("reviewed head", r["reason"])

    def test_clean_with_dirty_tree_is_stale(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A")
        head = self.commit("A")
        with open(os.path.join(self.wt("A"), "stray.txt"), "w") as f:
            f.write("x")
        self.g("record", "A", "1", self.workflow("clean", "wf-1", head))
        self.assertEqual(self.rows()["A"]["state"], "stale")
        self.assertIn("uncommitted", self.rows()["A"]["reason"])

    def test_status_rederives_stale_for_clean_unit(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A")
        head = self.commit("A")
        self.g("record", "A", "1", self.workflow("clean", "wf-1", head))
        self.assertEqual(json.loads(self.g("status", "--json"))[0]["state"], "clean")
        self.commit("A", "later.txt")
        st = json.loads(self.g("status", "--json"))[0]
        self.assertEqual(st["state"], "stale")
        self.assertIn("reviewed head", st["reason"])

    def test_status_rederives_stale_for_pr_open_unit(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A")
        head = self.commit("A")
        self.g("record", "A", "1", self.workflow("clean", "wf-1", head))
        self.g("set", "A", "pr-open", "--reason", "draft PR")
        self.assertEqual(json.loads(self.g("status", "--json"))[0]["state"], "pr-open")
        self.commit("A", "later.txt")
        st = json.loads(self.g("status", "--json"))[0]
        self.assertEqual(st["state"], "stale")
        self.assertIn("reviewed head", st["reason"])
        sh(self.wt("A"), "reset", "-q", "--soft", "HEAD~1")
        st = json.loads(self.g("status", "--json"))[0]
        self.assertEqual(st["state"], "stale")
        self.assertIn("uncommitted", st["reason"])

    def test_reviewer_without_structured_output_prevents_clean(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A")
        head = self.commit("A")

        def not_ok(value):
            value["runs"][1]["ok"] = False
        self.g("record", "A", "1", self.workflow("clean", "wf-1", head, not_ok))
        r = self.rows()["A"]
        self.assertEqual(r["state"], "stale")
        self.assertIn("review-1-1", r["reason"])

    def test_missing_required_second_reviewer_prevents_clean(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"], "effort": "exhaustive"}])
        self.started("A")
        head = self.commit("A")
        self.g("record", "A", "1", self.workflow("clean", "wf-1", head))
        self.assertEqual(self.rows()["A"]["state"], "stale")
        self.assertIn("review-1-2", self.rows()["A"]["reason"])

    def test_adopting_dirty_existing_worktree_blocks(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        sh(self.repo, "worktree", "add", "-q", "-b", "orchestrate/A", self.wt("A"), "main")
        with open(os.path.join(self.wt("A"), "dirt"), "w") as f:
            f.write("x")
        out = self.launch("A", "--adopt", code=3)
        self.assertEqual(out["state"], "blocked")
        self.assertIn("uncommitted", out["reason"])
        self.assertEqual(self.rows()["A"]["state"], "blocked")
        self.assertEqual(os.listdir(os.path.join(self.store, "args")) if os.path.isdir(
            os.path.join(self.store, "args")) else [], [])

    def test_adopting_wrong_branch_worktree_blocks(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        sh(self.repo, "worktree", "add", "-q", "-b", "other", self.wt("A"), "main")
        out = self.launch("A", "--adopt", code=3)
        self.assertIn("expected branch orchestrate/A", out["reason"])
        self.assertFalse(os.path.isdir(os.path.join(self.store, "args")))

    def test_existing_worktree_is_refused_without_adopt(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}, {"id": "B", "title": "b", "paths": ["b/*"]}])
        sh(self.repo, "worktree", "add", "-q", "-b", "orchestrate/A", self.wt("A"), "main")
        os.makedirs(self.wt("B"))
        with open(os.path.join(self.store, "units.tsv"), "rb") as f:
            tsv = f.read()
        for uid in ("A", "B"):
            p = self.cli("launch", uid, "--max", "2")
            self.assertEqual((p.returncode, p.stdout), (3, ""), p.stderr)
            self.assertIn(self.wt(uid), p.stderr)
            self.assertIn("--adopt", p.stderr)
        with open(os.path.join(self.store, "units.tsv"), "rb") as f:
            self.assertEqual(f.read(), tsv)
        self.assertFalse(os.path.isdir(os.path.join(self.store, "args")))
        self.assertEqual(self.launch("A", "--adopt")["attempt"], 1)

    def test_store_created_worktree_is_reused_by_a_later_attempt_without_adopt(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        head = self.commit("A")
        self.g("record", "A", "1", self.workflow("unresolved", "wf-1", head))
        spec = self.launch("A")
        self.assertEqual(spec["attempt"], 2)
        self.assertEqual(self.rows()["A"]["start_head"], head)

    def test_adopting_clean_existing_worktree_on_branch_launches(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        sh(self.repo, "worktree", "add", "-q", "-b", "orchestrate/A", self.wt("A"), "main")
        head = self.commit("A")
        spec = self.launch("A", "--adopt")
        self.assertTrue(os.path.exists(spec["args_path"]))
        self.assertEqual(self.rows()["A"]["start_head"], head)

    def test_unknown_dependency_blocks_until_imported(self):
        self.init()
        self.load([{"id": "B", "title": "b", "blockedBy": ["A"], "paths": ["b/*"]}])
        r = self.rows()["B"]
        self.assertEqual((r["state"], r["reason"]), ("blocked", "unknown dependency A"))
        self.assertEqual(self.next(), [])
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.assertEqual(self.rows()["B"]["state"], "queued")
        self.assertEqual(self.next(), ["A"])

    def test_dependency_must_be_merged_into_base(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]},
                   {"id": "B", "title": "b", "blockedBy": ["A"], "paths": ["b/*"]}])
        self.started("A")
        head = self.commit("A")
        self.g("record", "A", "1", self.workflow("clean", "wf-1", head))
        self.assertEqual(self.next(), [])
        self.g("set", "A", "merged", "--reason", "landed")
        self.assertEqual(self.next(), [], "head not yet in main")
        sh(self.repo, "merge", "-q", "--ff-only", "orchestrate/A")
        self.assertEqual(self.next(), ["B"])

    def test_exclusive_scheduling_without_paths(self):
        self.init()
        self.load([{"id": "X", "title": "x", "priority": 1},
                   {"id": "B", "title": "b", "priority": 2, "paths": ["b/*"]},
                   {"id": "C", "title": "c", "priority": 3, "paths": ["c/*"]}])
        self.assertEqual(self.next(), ["X"])
        self.launch("X", "--max", "3")
        self.assertEqual(self.next(), [])
        self.launch("B", "--force-window", code=3)
        self.g("set", "X", "parked", "--reason", "test")
        self.assertEqual(self.next(), [])
        self.g("set", "X", "queued", "--reason", "release", "--runs-dir", self.runs)
        self.assertEqual(self.next(), ["X"])
        self.g("set", "X", "parked", "--reason", "test")
        self.assertEqual(self.next(), ["B", "C"])
        self.launch("B")
        self.g("set", "X", "queued", "--reason", "requeue", "--runs-dir", self.runs)
        self.assertEqual(self.next(), ["C"])
        self.launch("X", "--force-window", code=3)

    def test_path_prefix_overlap(self):
        self.init()
        self.load([{"id": "A", "title": "a", "priority": 1, "paths": ["src/foo/*"]},
                   {"id": "B", "title": "b", "priority": 2, "paths": ["src/foo/bar.py"]},
                   {"id": "C", "title": "c", "priority": 3, "paths": ["docs/**"]},
                   {"id": "D", "title": "d", "priority": 4, "paths": ["src/f*"]}])
        self.assertEqual(self.next(), ["A", "C"])
        self.assertEqual(self.next(1), ["A"])
        self.launch("A")
        self.assertEqual(self.next(), ["C"])
        self.launch("B", "--force-window", code=3)

    def test_accepted_unmerged_unit_holds_its_paths(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["src/*"]},
                   {"id": "B", "title": "b", "paths": ["src/x.py"]}])
        self.started("A")
        head = self.commit("A")
        self.g("record", "A", "1", self.workflow("clean", "wf-1", head))
        self.assertEqual(self.next(), [])

    def test_next_json_gives_a_reason_for_each_unit_left_out(self):
        self.init()
        self.load([{"id": "A", "title": "a", "priority": 1, "paths": ["src/*"]},
                   {"id": "B", "title": "b", "priority": 2, "paths": ["src/x.py"]},
                   {"id": "C", "title": "c", "priority": 3, "paths": ["c/*"]},
                   {"id": "D", "title": "d", "blockedBy": ["A"], "paths": ["d/*"]}])
        out = json.loads(self.g("next", "--max", "1", "--json"))
        self.assertEqual(out["selected"], ["A"])
        self.assertEqual(sorted(out["refused"]), ["B", "C", "D"])
        self.assertEqual(out["refused"]["B"], "paths overlap A (picked)")
        self.assertEqual(out["refused"]["C"], "window full")
        self.assertIn("dependency A is queued", out["refused"]["D"])
        self.assertEqual(self.g("next", "--max", "1"), "A\n")

    def test_priority_order_puts_none_and_zero_last(self):
        self.init()
        self.load([{"id": "N", "title": "n", "paths": ["n/*"]},
                   {"id": "Z", "title": "z", "priority": 0, "paths": ["z/*"]},
                   {"id": "L", "title": "l", "priority": 4, "paths": ["l/*"]},
                   {"id": "U", "title": "u", "priority": 1, "paths": ["u/*"]}])
        self.assertEqual(self.next(10), ["U", "L", "N", "Z"])

    def test_claimed_units_never_launch(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"], "claimedBy": ["open PR 12"]}])
        self.assertEqual(self.next(), [])
        self.launch("A", "--force-window", code=3)
        self.assertEqual(self.rows()["A"]["state"], "queued")
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.assertEqual(self.next(), ["A"])

    def test_retry_until_max_attempts_then_parked(self):
        self.init("--max-attempts", "2")
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        head = self.commit("A")
        self.g("record", "A", "1", self.workflow("unresolved", "wf-1", head))
        self.assertEqual(self.rows()["A"]["state"], "unresolved")
        self.assertEqual(self.next(), ["A"])
        spec = self.started("A", "wf-2")
        self.assertEqual(spec["attempt"], 2)
        with open(spec["args_path"]) as f:
            brief = json.load(f)["brief"]
        with open(brief) as f:
            self.assertIn("attempt 2", f.read())
        self.g("record", "A", "2", self.workflow("unresolved", "wf-2", head))
        r = self.rows()["A"]
        self.assertEqual(r["state"], "parked")
        self.assertIn("attempt 2 of 2", r["reason"])
        self.assertEqual(self.next(), [])

    def test_reconcile_waits_and_never_relaunches_beside_a_live_child(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        self.stopped("wf-1")
        self.child("child-1", "wf-1", "A", os.getpid())
        out = self.reconcile()[0]
        self.assertEqual(out["action"], "wait", out)
        self.assertEqual(out["live"], ["child-1"])
        self.assertIn("child-1", out["reason"])
        self.assertNotIn("args_path", out)

    def test_reconcile_stopped_workflow_with_dead_child_retries(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        status = self.stopped("wf-1")
        self.child("child-1", "wf-1", "A", self.dead_pid())
        out = json.loads(self.g("reconcile", "--runs-dir", self.runs, "--json"))[0]
        self.assertEqual(out["action"], "retry", out)
        self.assertEqual(out["file"], status)
        self.g("record", "A", "1", status)
        self.assertEqual(self.rows()["A"]["state"], "run-failed")
        self.assertEqual(self.next(), ["A"])

    def test_reconcile_live_child_of_unknown_owner_holds(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        self.stopped("wf-1")
        self.child("child-1", "someone-else", "A", os.getpid())
        out = json.loads(self.g("reconcile", "--runs-dir", self.runs, "--json"))[0]
        self.assertEqual(out["action"], "hold", out)

    def test_reconcile_wait_record_and_missing(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        out = json.loads(self.g("reconcile", "--runs-dir", self.runs, "--json"))[0]
        self.assertEqual(out["action"], "hold", "bound run with no status and no writer")

        def running(doc):
            doc.update(state="running", pid=os.getpid())
            del doc["workflow"]["value"]
        self.fixture("clean", "wf-1", running)
        out = json.loads(self.g("reconcile", "--runs-dir", self.runs, "--json"))[0]
        self.assertEqual(out["action"], "wait", out)
        shutil.rmtree(os.path.join(self.runs, "wf-1"))
        status = self.workflow("clean", "wf-1", "abc")
        out = json.loads(self.g("reconcile", "--runs-dir", self.runs, "--json"))[0]
        self.assertEqual((out["action"], out["file"]), ("record", status))

    def reconcile(self):
        return json.loads(self.g("reconcile", "--runs-dir", self.runs, "--json"))

    def running_workflow(self, run, args=None):
        def edit(doc):
            doc.update(state="running", pid=os.getpid())
            del doc["workflow"]["value"]
            if args is not None:
                doc["workflow"]["args"] = args
                doc["steps"] = []
        return self.fixture("clean", run, edit)

    def test_parked_live_attempt_keeps_reservation_until_writers_end(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A")
        self.stopped("wf-1")
        child = self.child("child-1", "wf-1", "A", os.getpid())
        self.g("set", "A", "parked", "--reason", "pause")
        out = self.reconcile()
        self.assertEqual([(d["id"], d["action"]) for d in out], [("A", "hold")], out)
        self.assertIn("child-1", out[0]["reason"])
        self.g("set", "A", "queued", "--reason", "resume", code=3)
        self.g("set", "A", "queued", "--reason", "resume", "--runs-dir", self.runs, code=3)
        self.assertEqual(self.rows()["A"]["state"], "parked")
        self.assertEqual(self.next(), [])
        doc = orchestrate.read_json(child)
        doc.update(state="complete", pid=self.dead_pid())
        orchestrate.write_json(child, doc)
        self.assertNotIn("child-1", self.reconcile()[0]["reason"])
        self.g("set", "A", "queued", "--reason", "resume", "--runs-dir", self.runs)
        self.assertEqual(self.reconcile(), [])
        self.assertEqual(self.launch("A")["attempt"], 2)

    def test_reconcile_waits_while_an_older_bound_controller_runs(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        self.running_workflow("wf-1")
        self.g("bind", "A", "1", "wf-2")
        self.stopped("wf-2", child=None)
        out = self.reconcile()[0]
        self.assertEqual((out["action"], out["live"]), ("wait", ["wf-1"]), out)

    def test_reconcile_holds_for_nonterminal_child_with_unknown_pid(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        self.stopped("wf-1")
        for parent in ("someone-else", "wf-1"):
            shutil.rmtree(os.path.join(self.runs, "child-1"), ignore_errors=True)
            path = self.child("child-1", parent, "A", os.getpid())
            doc = orchestrate.read_json(path)
            doc.pop("pid")
            orchestrate.write_json(path, doc)
            out = self.reconcile()[0]
            self.assertEqual(out["action"], "hold", (parent, out))
            self.assertIn("child-1", out["reason"])

    def test_failed_run_with_commits_or_structured_output_holds(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        self.stopped("wf-1", edit=lambda d: d.update(state="failed"))
        child = self.child("child-1", "wf-1", "A", self.dead_pid(), state="complete")
        output = os.path.join(os.path.dirname(child), "structured-output", "x", "output.json")
        os.makedirs(os.path.dirname(output))
        orchestrate.write_json(output, {"status": "done", "head": "h", "summary": "s"})
        out = self.reconcile()[0]
        self.assertEqual(out["action"], "hold", out)
        self.assertIn(output, out["reason"])
        shutil.rmtree(os.path.dirname(output))
        self.assertEqual(self.reconcile()[0]["action"], "retry")
        self.commit("A")
        out = self.reconcile()[0]
        self.assertEqual(out["action"], "hold", out)
        self.assertIn("1 commits since start head", out["reason"])

    def test_held_finished_work_is_recorded_then_retried_from_the_kept_commit(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        status = self.stopped("wf-1", edit=lambda d: d.update(state="failed"))
        self.child("child-1", "wf-1", "A", self.dead_pid(), state="complete")
        head = self.commit("A")
        self.assertEqual(self.reconcile()[0]["action"], "hold")
        self.g("set", "A", "queued", "--reason", "keep", "--runs-dir", self.runs, code=3)
        self.g("record", "A", "1", status)
        self.assertEqual(self.rows()["A"]["state"], "run-failed")
        self.assertEqual(self.next(), ["A"])
        spec = self.launch("A")
        self.assertEqual(spec["attempt"], 2)
        self.assertEqual(sh(self.wt("A"), "rev-parse", "HEAD"), head)
        with open(orchestrate.read_json(spec["args_path"])["brief"]) as f:
            self.assertIn("git log", f.read())

    def test_merged_dependency_without_recorded_head_blocks(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]},
                   {"id": "B", "title": "b", "blockedBy": ["A"], "paths": ["b/*"]}])
        self.g("set", "A", "merged", "--reason", "landed elsewhere")
        self.assertEqual(self.next(), [])
        self.launch("B", code=3)

    def test_accepted_unit_without_paths_reserves_everything(self):
        self.init()
        self.load([{"id": "A", "title": "a"}, {"id": "B", "title": "b", "paths": ["b/*"]}])
        self.started("A")
        self.g("record", "A", "1", self.workflow("clean", "wf-1", self.commit("A")))
        self.assertEqual(self.rows()["A"]["state"], "clean")
        self.assertEqual(self.next(), [])

    def test_candidate_without_paths_waits_for_accepted_unit(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["b/*"]}, {"id": "B", "title": "b"}])
        self.started("A")
        self.g("record", "A", "1", self.workflow("clean", "wf-1", self.commit("A")))
        self.assertEqual(self.rows()["A"]["state"], "clean")
        self.assertEqual(self.next(), [])

    def test_crash_after_args_before_launch_record_resumes_same_attempt(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        workflow = os.path.join(self.tmp, "custom-loop.js")
        args_path = os.path.join(self.store, "args", "A-1.json")
        real_write = orchestrate.atomic_write

        def crash_after_args(path, text):
            if os.path.exists(args_path):
                raise RuntimeError("simulated crash")
            real_write(path, text)
        a = orchestrate.parser().parse_args(["--store", self.store, "launch", "A", "--workflow", workflow])
        with mock.patch.object(orchestrate, "atomic_write", side_effect=crash_after_args), \
                mock.patch("sys.stdout", new=open(os.devnull, "w")):
            try:
                orchestrate.cmd_launch(self.store, a)
            except RuntimeError:
                pass
        with open(args_path, "rb") as f:
            before = f.read()
        out = self.reconcile()[0]
        self.assertEqual(out["action"], "relaunch-same-args", out)
        self.assertEqual((out["args_path"], out["workflow"]), (args_path, workflow))
        self.assertEqual(self.rows()["A"]["start_head"], sh(self.repo, "rev-parse", "main"))
        with open(args_path, "rb") as f:
            self.assertEqual(f.read(), before)
        self.g("bind", "A", "1", "wf-1")

    def test_record_refuses_an_older_bound_run_while_running(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        self.g("bind", "A", "1", "wf-2")
        old = self.stopped("wf-1")
        self.running_workflow("wf-2")
        self.child("child-2", "wf-2", "A", os.getpid())
        self.g("record", "A", "1", old, code=3)
        r = self.rows()["A"]
        self.assertEqual((r["state"], r["attempt"]), ("running", 1))
        self.assertEqual(self.next(), [])

    def test_record_refuses_while_an_older_bound_controller_runs(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        self.running_workflow("wf-1")
        self.g("bind", "A", "1", "wf-2")
        latest = self.stopped("wf-2", child=None)
        self.g("record", "A", "1", latest, code=3)
        self.assertEqual(self.rows()["A"]["state"], "running")
        self.assertEqual(self.next(), [])
        self.launch("A", "--force-window", code=3)

    def test_record_refuses_while_a_bound_child_runs(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        head = self.commit("A")
        status = self.workflow("unresolved", "wf-1", head)
        child = self.child("child-1", "wf-1", "A", os.getpid())
        out = self.reconcile()[0]
        self.assertEqual((out["action"], out["live"]), ("wait", ["child-1"]), out)
        self.g("record", "A", "1", status, code=3)
        self.g("record", "A", "1", status, "--runs-dir", self.runs, code=3)
        self.assertEqual(self.rows()["A"]["state"], "running")
        self.assertFalse(os.path.exists(os.path.join(self.store, "receipts", "A-1.json")))
        self.launch("A", "--force-window", code=3)
        doc = orchestrate.read_json(child)
        doc.update(state="complete", pid=self.dead_pid())
        orchestrate.write_json(child, doc)
        self.assertEqual(self.reconcile()[0]["action"], "record")
        self.g("record", "A", "1", status)
        self.assertEqual(self.rows()["A"]["state"], "unresolved")
        self.assertEqual(self.launch("A")["attempt"], 2)

    def test_parked_reserved_attempt_keeps_its_paths_and_window_slot(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}, {"id": "B", "title": "b", "paths": ["a/b"]},
                   {"id": "C", "title": "c", "paths": ["c/*"]}])
        self.started("A")
        self.stopped("wf-1")
        self.child("child-1", "wf-1", "A", os.getpid())
        self.g("set", "A", "parked", "--reason", "pause")
        self.assertEqual(self.rows()["A"]["reserved"], "1")
        self.assertEqual(self.next(3), ["C"])
        self.assertEqual(self.next(1), [])
        self.launch("B", "--force-window", code=3)

    def test_parked_reserved_attempt_without_paths_excludes_everything(self):
        self.init()
        self.load([{"id": "A", "title": "a"}, {"id": "B", "title": "b", "paths": ["a/*"]}])
        self.started("A")
        self.stopped("wf-1")
        self.child("child-1", "wf-1", "A", os.getpid())
        self.g("set", "A", "parked", "--reason", "pause")
        self.assertEqual(self.reconcile()[0]["action"], "hold")
        self.assertEqual(self.next(), [])
        self.launch("B", "--force-window", code=3)

    def test_child_named_by_controller_without_status_keeps_ownership(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")

        def running_ref(doc):
            doc["steps"][0]["status"] = "running"
            doc["workflowChildren"]["children"][0]["state"] = "running"
        status = self.stopped("wf-1", child="child-missing", edit=running_ref)
        out = self.reconcile()[0]
        self.assertEqual(out["action"], "hold", out)
        self.assertIn("child-missing", out["reason"])
        self.g("record", "A", "1", status, code=3)
        self.g("set", "A", "parked", "--reason", "pause")
        self.g("set", "A", "queued", "--reason", "resume", "--runs-dir", self.runs, code=3)
        self.launch("A", "--force-window", code=3)
        self.child("child-missing", "wf-1", "A", self.dead_pid(), state="complete")
        self.g("set", "A", "queued", "--reason", "resume", "--runs-dir", self.runs)
        self.assertEqual(self.launch("A")["attempt"], 2)

    def test_later_controller_collecting_a_child_resolves_an_older_stopped_reference(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        self.stopped("wf-1", child="child-shared")
        self.g("bind", "A", "1", "wf-2")
        head = self.commit("A")
        status = self.workflow("unresolved", "wf-2", head)
        doc = orchestrate.read_json(status)
        shared = doc["steps"][0]["runId"]
        for ref in doc["steps"] + doc["workflowChildren"]["children"]:
            if ref["runId"] == shared:
                ref["runId"] = "child-shared"
        orchestrate.write_json(status, doc)
        out = self.reconcile()[0]
        self.assertEqual(out["action"], "record", out)
        self.g("record", "A", "1", status)
        self.assertEqual(self.rows()["A"]["state"], "unresolved")

    def test_collected_child_without_status_still_surfaces_its_structured_output(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        self.stopped("wf-1", child="child-shared")
        self.g("bind", "A", "1", "wf-2")

        def failed_after_collecting(doc):
            doc["state"] = "failed"
            doc["steps"][0]["status"] = "completed"
            doc["workflowChildren"]["children"][0]["state"] = "completed"
        self.stopped("wf-2", child="child-shared", edit=failed_after_collecting)
        output = os.path.join(self.runs, "child-shared", "structured-output", "result", "output.json")
        os.makedirs(os.path.dirname(output))
        orchestrate.write_json(output, {"status": "done", "head": "h", "summary": "s"})
        out = self.reconcile()[0]
        self.assertEqual(out["action"], "hold", out)
        self.assertIn(output, out["reason"])

    def test_launching_with_unbound_live_workflow_for_the_unit_holds(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        spec = self.launch("A")
        with open(spec["args_path"]) as f:
            args = json.load(f)
        self.running_workflow("wf-x", args)
        out = self.reconcile()[0]
        self.assertEqual(out["action"], "hold", out)
        self.assertIn("wf-x", out["reason"])

    def test_store_with_a_session_column_still_loads(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        path = os.path.join(self.store, "units.tsv")
        with open(path) as f:
            lines = f.read().splitlines()
        with open(path, "w") as f:
            f.write("\n".join([lines[0] + "\tsession"] + [l + "\tsess-old" for l in lines[1:]]) + "\n")
        r = self.rows()["A"]
        self.assertEqual((r["state"], r["run"], r["attempt"]), ("running", "wf-1", 1))
        self.assertNotIn("session", r)
        self.g("bind", "A", "1", "wf-2")
        with open(path) as f:
            self.assertNotIn("sess-old", f.read())
        self.assertEqual(self.rows()["A"]["run"], "wf-1,wf-2")

    def ended_workflow(self, run, uid, attempt, state="stopped"):
        """A terminal workflow with no return value whose args are uid's stored args for attempt."""
        args = orchestrate.read_json(os.path.join(self.store, "args", "%s-%d.json" % (uid, attempt)))

        def edit(doc):
            doc["state"] = state
            doc["workflow"]["args"] = args
        return self.stopped(run, child=None, edit=edit)

    def test_launching_with_an_ended_unbound_workflow_for_the_attempt_holds(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.launch("A")
        self.ended_workflow("wf-x", "A", 1, state="failed")
        out = self.reconcile()[0]
        self.assertEqual(out["action"], "hold", out)
        self.assertIn("wf-x", out["reason"])
        self.assertIn("bind A 1 wf-x", out["reason"])
        self.assertNotIn("args_path", out)
        self.g("bind", "A", "1", "wf-x")
        self.assertEqual(self.reconcile()[0]["action"], "retry")

    def test_running_with_a_newer_ended_unbound_workflow_for_the_attempt_holds(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        self.stopped("wf-1")
        self.child("child-1", "wf-1", "A", self.dead_pid())
        self.assertEqual(self.reconcile()[0]["action"], "retry")
        self.ended_workflow("wf-2", "A", 1, state="failed")
        out = self.reconcile()[0]
        self.assertEqual(out["action"], "hold", out)
        self.assertIn("bind A 1 wf-2", out["reason"])
        self.assertNotIn("file", out)

    def test_ended_unbound_workflow_older_than_the_bound_run_holds_and_binding_it_keeps_the_newer_outcome(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        head = self.commit("A")
        self.workflow("unresolved", "wf-1", head)
        bound_start = orchestrate.read_json(os.path.join(self.runs, "wf-1", "status.json"))["startedAt"]
        path = self.ended_workflow("wf-0", "A", 1, state="failed")
        doc = orchestrate.read_json(path)
        doc["startedAt"] = bound_start - 1000
        orchestrate.write_json(path, doc)
        out = self.reconcile()[0]
        self.assertEqual(out["action"], "hold", out)
        self.assertIn("bind A 1 wf-0", out["reason"])
        self.g("bind", "A", "1", "wf-0")
        out = self.reconcile()[0]
        self.assertEqual(out["action"], "record", out)
        self.assertIn("wf-1", out["reason"])
        self.g("record", "A", "1", path, "--runs-dir", self.runs, code=3)
        self.assertEqual(self.rows()["A"]["state"], "running", "the older bound run is superseded")
        self.g("record", "A", "1", out["file"])
        self.assertEqual(self.rows()["A"]["state"], "unresolved")

    def test_ended_workflow_of_an_earlier_attempt_does_not_hold_the_next(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.started("A", "wf-1")
        status = self.ended_workflow("wf-1", "A", 1)
        self.g("record", "A", "1", status)
        self.assertEqual(self.rows()["A"]["state"], "run-failed")
        self.launch("A")
        out = self.reconcile()[0]
        self.assertEqual(out["action"], "relaunch-same-args", out)

    def test_set_refuses_live_attempt_except_parked(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.launch("A")
        self.g("set", "A", "queued", "--reason", "x", code=3)
        self.g("set", "A", "clean", "--reason", "x", code=2)
        self.g("set", "A", "parked", "--reason", "stuck")
        self.assertEqual((self.rows()["A"]["state"], self.rows()["A"]["reason"]), ("parked", "stuck"))

    def test_import_keeps_state_and_attempts_and_applies_updates(self):
        self.init()
        self.load([{"id": "A", "title": "a", "paths": ["a/*"]}])
        self.launch("A")
        self.load([{"id": "A", "title": "renamed", "paths": ["b/*"]}])
        r = self.rows()["A"]
        self.assertEqual((r["state"], r["attempt"], r["paths"]), ("launching", 1, "b/*"))
        with open(os.path.join(self.store, "units.json")) as f:
            self.assertEqual(json.load(f)[0]["title"], "renamed")

    def test_import_rejects_invalid_units(self):
        self.init()
        for bad in ([{"id": "a/b", "title": "t"}], [{"id": "A"}], [{"id": "A", "title": "t", "priority": 9}],
                    [{"id": "A", "title": "t", "blockedBy": ["A"]}], {"id": "A"},
                    [{"id": "A", "title": "t"}, {"id": "A", "title": "u"}]):
            path = os.path.join(self.tmp, "bad.json")
            with open(path, "w") as f:
                json.dump(bad, f)
            self.g("import", path, code=2)
        self.assertEqual(self.rows(), {})

    def test_quick_effort_is_rejected_because_it_runs_no_reviewers(self):
        self.g("init", "--repo", self.repo, "--base", "main", "--worktrees", os.path.join(self.tmp, "wt"),
               "--effort", "quick", code=2)
        self.assertFalse(os.path.exists(os.path.join(self.store, "config.json")))
        self.init()
        path = os.path.join(self.tmp, "quick.json")
        with open(path, "w") as f:
            json.dump([{"id": "A", "title": "t", "effort": "quick"}], f)
        p = self.cli("import", path)
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn("standard or exhaustive", p.stderr)
        self.assertEqual(self.rows(), {})

    def test_init_grant_records_exact_text(self):
        self.init("--grant", "push branches and open draft PRs")
        with open(os.path.join(self.store, "standing.md")) as f:
            text = f.read()
        self.assertIn('4. Authority granted by the user on', text)
        self.assertIn('"push branches and open draft PRs"', text)
        self.init()
        with open(os.path.join(self.store, "standing.md")) as f:
            self.assertEqual(f.read(), text)
        self.g("init", "--repo", self.repo, "--base", "main", "--worktrees", "/elsewhere", code=3)

    def test_lock_serializes_commands(self):
        self.init()
        with open(os.path.join(self.store, ".lock"), "a+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            with self.assertRaises(subprocess.TimeoutExpired):
                self.cli("status", timeout=1)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        self.g("status")

    def test_fixtures_carry_no_runtime_identifiers(self):
        pattern = re.compile("tool" + r"u_[A-Za-z0-9]+|uid-[0-9]+")
        for root, _, files in os.walk(FIXTURES):
            for fn in files:
                with open(os.path.join(root, fn)) as f:
                    self.assertEqual(pattern.findall(f.read()), [], os.path.join(root, fn))

    def test_atomic_write_leaves_no_partial_file(self):
        path = os.path.join(self.tmp, "d", "units.tsv")
        orchestrate.atomic_write(path, "old\n")
        with mock.patch.object(orchestrate.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                orchestrate.atomic_write(path, "new contents that must not appear\n")
        with open(path) as f:
            self.assertEqual(f.read(), "old\n")
        self.assertEqual(os.listdir(os.path.dirname(path)), ["units.tsv"])


if __name__ == "__main__":
    unittest.main()
