import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "kaizen-tokens.py")
RUN_ID = "11111111-2222-3333-4444-555555555555"

spec = importlib.util.spec_from_file_location("kaizen_tokens", SCRIPT)
kt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kt)


def usage(inp=0, cr=0, cw=0, out=10, cost_cw=0.0, cw1h=0):
    return {"input": inp, "output": out, "cacheRead": cr, "cacheWrite": cw, "cacheWrite1h": cw1h,
            "cost": {"input": 0.0, "output": 0.01, "cacheRead": cr / 1e6, "cacheWrite": cost_cw,
                     "total": 0.01 + cr / 1e6 + cost_cw}}


class Builder:
    def __init__(self, cwd="/w"):
        self.lines = [{"type": "session", "version": 3, "id": "x", "timestamp": "2026-10-01T10:00:00.000Z", "cwd": cwd}]
        self.minute = 0

    def ts(self, minutes=1):
        self.minute += minutes
        h, m = divmod(self.minute, 60)
        return "2026-10-01T%02d:%02d:00.000Z" % (10 + h, m)

    def system(self, sections, tools):
        self.lines.append({"type": "message", "timestamp": self.ts(0),
                           "message": {"role": "system", "content": "", "sections": sections, "toolsAdded": tools}})
        return self

    def user(self, text):
        self.lines.append({"type": "message", "timestamp": self.ts(0),
                           "message": {"role": "user", "content": [{"type": "text", "text": text}]}})
        return self

    def turn(self, u, calls=(), model="m1", gap=1):
        content = [{"type": "toolCall", "id": cid, "name": name, "arguments": args} for cid, name, args in calls]
        self.lines.append({"type": "message", "timestamp": self.ts(gap), "message": {
            "role": "assistant", "content": content, "usage": u, "provider": "p", "model": model}})
        return self

    def result(self, cid, name, text):
        self.lines.append({"type": "message", "timestamp": self.ts(0), "message": {
            "role": "toolResult", "toolCallId": cid, "toolName": name, "content": [{"type": "text", "text": text}]}})
        return self

    def event(self, kind, **extra):
        self.lines.append({"type": kind, "timestamp": self.ts(0), **extra})
        return self

    def custom(self, content):
        self.lines.append({"type": "custom_message", "customType": "notify", "timestamp": self.ts(0), "content": content})
        return self

    def structured(self, cid, value, error=False):
        self.turn(usage(inp=5, cr=2000, cw=50), calls=[(cid, "structured_output", {"value": value})])
        self.lines.append({"type": "message", "timestamp": self.ts(0), "message": {
            "role": "toolResult", "toolCallId": cid, "toolName": "structured_output", "isError": error,
            "content": [{"type": "text", "text": "ok"}]}})
        return self

    def write(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("\n".join(json.dumps(x) for x in self.lines) + "\n")


def fake_root(d):
    root = os.path.join(d, "hworks")
    os.makedirs(os.path.join(root, "extensions"))
    os.makedirs(os.path.join(root, "agents"))
    os.makedirs(os.path.join(root, "global"))
    with open(os.path.join(root, "extensions", "mode.ts"), "w") as f:
        f.write('if (on) sections.hw_mode = SECTION;\npi.registerTool({\n  name: "hw_tool",\n  label: "x" });\n')
    with open(os.path.join(root, "extensions", "mode.test.mts"), "w") as f:
        f.write("sections.test_only = 1;\n")
    open(os.path.join(root, "agents", "coder.md"), "w").close()
    open(os.path.join(root, "global", "AGENTS.md"), "w").close()
    return root


def sections(root):
    hw = os.path.join(root, "global", "AGENTS.md")
    return {
        "preamble": "P" * 400,
        "project_context": ("<project_context>\n"
                            f'<project_instructions path="{hw}">' + "H" * 1200 + "</project_instructions>\n"
                            '<project_instructions path="/elsewhere/AGENTS.md">' + "L" * 800 + "</project_instructions>\n"
                            "</project_context>"),
        "acme-skills": ("<available_skills>Skill locations below are relative to /base/;\n"
                        "<skill><name>vendor-skill</name><location>/opt/x/node_modules/@acme/agent/skills/v/SKILL.md"
                        "</location>" + "V" * 300 + "</skill>\n"
                        f"<skill><name>own-skill</name><location>{root}/skills/own/SKILL.md</location>" + "O" * 200 +
                        "</skill></available_skills>"),
        "acme-guidance": "G" * 600,
        "hw_mode": "M" * 100,
    }


TOOLS = [{"name": "bash", "description": "B" * 300}, {"name": "fastgrep", "description": "F" * 500},
         {"name": "hw_tool", "description": "T" * 100}]


def main_session(root, cat_size=4000):
    """Three turns, a cat result carried two turns, then a compaction and a model change."""
    b = Builder().system(sections(root), TOOLS).user("U" * 100)
    b.turn(usage(inp=5, cw=3000, cost_cw=0.03), calls=[("c1", "bash", {"command": "cd /w && cat big.txt | head"})])
    b.result("c1", "bash", "x" * cat_size)
    b.turn(usage(inp=5, cr=3000, cw=2100), calls=[("c2", "bash", {"command": "ls"})])
    b.result("c2", "bash", "y" * 40)
    b.turn(usage(inp=5, cr=5100, cw=100))
    b.event("compaction", summary="s")
    b.turn(usage(inp=5, cr=0, cw=2500, cost_cw=0.025))
    b.event("model_change", provider="p", modelId="m2")
    b.turn(usage(inp=5, cr=0, cw=2600, cost_cw=0.026), model="m2")
    b.turn(usage(inp=5, cr=0, cw=2700, cost_cw=0.027), model="m2", gap=120)
    b.turn(usage(inp=5, cr=0, cw=2800, cost_cw=0.028), model="m2")
    return b


class Owners(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = fake_root(self.tmp.name)
        self.o = kt.Owners(self.root, rules=[])

    def tearDown(self):
        self.tmp.cleanup()

    def test_paths(self):
        self.assertEqual(self.o.path(os.path.join(self.root, "global", "AGENTS.md")), "hworks")
        self.assertEqual(self.o.path("/opt/x/node_modules/@acme/agent/skills/v/SKILL.md"), "upstream:@acme/agent")
        self.assertEqual(self.o.path("/opt/x/node_modules/plain/a.md"), "upstream:plain")
        self.assertEqual(self.o.path("/elsewhere/AGENTS.md"), "local")

    def test_link_into_hworks_is_hworks(self):
        link = os.path.join(self.tmp.name, "linked.md")
        os.symlink(os.path.join(self.root, "global", "AGENTS.md"), link)
        self.assertEqual(self.o.path(link), "hworks")

    def test_sections_tools_agents(self):
        self.assertEqual(self.o.section("hw_mode"), "hworks")
        self.assertEqual(self.o.section("test_only"), "upstream:unattributed")
        self.assertEqual(self.o.section("preamble"), "upstream:pi")
        self.assertEqual(self.o.section("acme-guidance"), "upstream:acme")
        self.assertEqual(self.o.section("odd_name"), "upstream:unattributed")
        self.assertEqual(self.o.tool("hw_tool"), "hworks")
        self.assertEqual(self.o.tool("bash"), "upstream:pi")
        self.assertEqual(self.o.tool("fastgrep"), "upstream:unattributed")
        self.assertEqual(self.o.agent("coder"), "hworks")
        self.assertEqual(self.o.agent("babysitter"), "local")

    def test_owner_map_wins_first_match(self):
        o = kt.Owners(self.root, rules=[("tool:fast", "upstream:acme"), ("tool:fastgrep", "upstream:other"),
                                        ("section:hw_mode", "local"), ("/elsewhere/", "upstream:acme")])
        self.assertEqual(o.tool("fastgrep"), "upstream:acme")
        self.assertEqual(o.section("hw_mode"), "local")
        self.assertEqual(o.path("/elsewhere/AGENTS.md"), "upstream:acme")

    def test_owner_map_from_env(self):
        old = os.environ.get("HWORKS_OWNER_MAP")
        os.environ["HWORKS_OWNER_MAP"] = "section:acme-=upstream:acme-co, tool:fastgrep=upstream:acme-co,bad"
        try:
            self.assertEqual(kt.owner_rules(), [("section:acme-", "upstream:acme-co"), ("tool:fastgrep", "upstream:acme-co")])
        finally:
            if old is None:
                del os.environ["HWORKS_OWNER_MAP"]
            else:
                os.environ["HWORKS_OWNER_MAP"] = old


class Report(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        cls.root = fake_root(d)
        cls.sroot = os.path.join(d, "sessions")
        for k in range(3):
            main_session(cls.root).write(os.path.join(cls.sroot, "proj", f"s{k}.jsonl"))
        child = Builder().system({"preamble": '<active_agent name="coder"/>' + "C" * 200}, TOOLS[:1]).user("brief")
        child.event("session_info", name=f"subagent-coder-{RUN_ID}-1")
        child.turn(usage(inp=5, cw=2500, cost_cw=0.02)).turn(usage(inp=5, cr=2500, cw=50))
        child.write(os.path.join(cls.sroot, "proj", "s0", RUN_ID, "run-0", "session.jsonl"))
        dup = Builder().turn(usage(inp=5, cw=99999, cost_cw=9.0))
        dup.write(os.path.join(cls.sroot, "proj", "subagent-artifacts", f"{RUN_ID}_coder_transcript.jsonl"))
        cls.owners = kt.Owners(cls.root, rules=[])
        cls.report, cls.notes = kt.analyze({"sessions": cls.sroot}, kt.ks.parse_since("2026-09-01"),
                                           min_sessions=3, top=50, root=cls.root, owners=cls.owners)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def row(self, section, **match):
        rows = [r for r in self.report[section] if all(r.get(k) == v for k, v in match.items())]
        return rows[0] if rows else None

    def test_artifact_copies_are_skipped_and_children_named(self):
        st = self.report["stats"]
        self.assertEqual((st["sessions"], st["main"]), (4, 3))
        self.assertIsNotNone(self.row("totals", group="kind child:coder"))
        self.assertLess(self.row("totals", group="all")["cost"], 5)

    def test_totals_add_up(self):
        all_ = self.row("totals", group="all")
        self.assertEqual(all_["turns"], 3 * 7 + 2)
        self.assertEqual(all_["cache write"], 3 * (3000 + 2100 + 100 + 2500 + 2600 + 2700 + 2800) + 2550)
        self.assertEqual(self.row("totals", group="kind main")["turns"], 21)
        self.assertEqual(self.row("totals", group="model p/m2")["turns"], 9)

    def test_calibration_uses_first_turns(self):
        s = kt.read_session(os.path.join(self.sroot, "proj", "s0.jsonl"), kt.ks.parse_since("2026-09-01"), [])
        chars = kt.system_chars(s) + kt.tool_chars(s) + s["pre_chars"]
        self.assertEqual(s["pre_chars"], 100)
        child = kt.read_session(os.path.join(self.sroot, "proj", "s0", RUN_ID, "run-0", "session.jsonl"),
                                kt.ks.parse_since("2026-09-01"), [])
        cchars = kt.system_chars(child) + kt.tool_chars(child) + child["pre_chars"]
        want = sorted([chars / 3005] * 3 + [cchars / 2505])
        self.assertAlmostEqual(self.report["stats"]["chars_per_token"], round((want[1] + want[2]) / 2, 2))

    def test_baseline_splits_parts_with_owners(self):
        cpt = self.report["stats"]["chars_per_token"]
        hw = self.row("baseline", kind="instructions", name=os.path.join(self.root, "global", "AGENTS.md"))
        self.assertEqual((hw["owner"], hw["sessions"]), ("hworks", 3))
        self.assertAlmostEqual(hw["median_tokens"], 1200 / cpt, delta=1200 / cpt / 100)
        self.assertEqual(hw["token_turns"], 3 * 7 * hw["median_tokens"])
        self.assertEqual(self.row("baseline", kind="instructions", name="/elsewhere/AGENTS.md")["owner"], "local")
        self.assertEqual(self.row("baseline", kind="skill", name="vendor-skill")["owner"], "upstream:@acme/agent")
        self.assertEqual(self.row("baseline", kind="skill", name="own-skill")["owner"], "hworks")
        self.assertEqual(self.row("baseline", kind="section", name="hw_mode")["owner"], "hworks")
        self.assertEqual(self.row("baseline", kind="tool", name="fastgrep")["owner"], "upstream:unattributed")
        frame = self.row("baseline", kind="section", name="acme-skills")
        self.assertLess(frame["median_tokens"], round(500 / cpt))

    def test_child_preamble_is_its_agent_prompt(self):
        tmp = self.report
        rep, _ = kt.analyze({"sessions": self.sroot}, kt.ks.parse_since("2026-09-01"), min_sessions=1, top=50,
                            root=self.root, owners=self.owners)
        self.report = rep
        try:
            self.assertEqual(self.row("baseline", kind="agent prompt", name="coder")["owner"], "hworks")
            self.assertEqual(self.row("baseline", kind="section", name="preamble")["sessions"], 3)
        finally:
            self.report = tmp

    def test_tool_results_are_carried_until_compaction(self):
        cpt = self.report["stats"]["chars_per_token"]
        r = self.row("tool results", shape="bash: cat | head")
        self.assertEqual((r["sessions"], r["calls"], r["tool_owner"]), (3, 3, "upstream:pi"))
        self.assertEqual(r["carried_token_turns"], r["tokens"] * 2)
        self.assertAlmostEqual(r["tokens"], 3 * 4000 / cpt, delta=3 * 4000 / cpt / 100)
        self.assertEqual(self.report["tool results"][0]["shape"], "bash: cat | head")

    def test_cache_rewrite_causes(self):
        causes = {r["cause"]: (r["turns"], r["sessions"]) for r in self.report["cache writes"]}
        self.assertEqual(causes, {"session start": (3, 3), "compaction": (3, 3), "model change": (3, 3),
                                  "idle past cache lifetime": (3, 3), "unexplained": (3, 3),
                                  "subagent start": (1, 1)})
        self.assertEqual(self.row("cache writes", cause="session start")["cost"], 0.09)

    def test_upstream_flags_only_upstream_rows(self):
        owners = {r["owner"] for r in self.report["upstream"]}
        self.assertTrue(owners)
        self.assertTrue(all(o.startswith("upstream:") for o in owners), owners)
        self.assertIn("upstream:pi or provider", owners)
        self.assertIn(("upstream:unattributed", "tool fastgrep"), {(r["owner"], r["what"]) for r in self.report["upstream"]})


    def test_long_context_share_by_threshold(self):
        rep, _ = kt.analyze({"sessions": self.sroot}, kt.ks.parse_since("2026-09-01"), min_sessions=3, top=50,
                            root=self.root, owners=self.owners, long_context=5000)
        rows = {r["group"]: r for r in rep["long context"]}
        all_ = self.row("totals", group="all")
        long_cost = 3 * ((0.01 + 0.003) + (0.01 + 0.0051))
        self.assertEqual((rows["all"]["long_turns"], rows["main"]["long_turns"], rows["subagent"]["long_turns"]),
                         (6, 6, 0))
        self.assertAlmostEqual(rows["all"]["long_cost"], round(long_cost, 2))
        self.assertAlmostEqual(rows["all"]["long_share"], round(round(long_cost, 2) / all_["cost"], 3), delta=0.01)
        self.assertGreater(rows["all"]["long_share"], 0)
        self.assertEqual(rows["subagent"]["long_cost"], 0)
        top = rep["long context sessions"]
        self.assertEqual(len(top), 3)
        self.assertEqual((top[0]["long_turns"], top[0]["compactions"], top[0]["kind"]), (2, 1, "main"))
        self.assertTrue(top[0]["session"].startswith("proj/s"))
        self.assertEqual(self.report["long context"][0]["long_turns"], 0)
        self.assertEqual(self.report["long context"][0]["threshold"], 150000)
        self.assertEqual(self.report["long context sessions"], [])

    def test_since_and_cwd_filters(self):
        none, _ = kt.analyze({"sessions": self.sroot}, kt.ks.parse_since("2027-01-01"), root=self.root, owners=self.owners)
        self.assertEqual(none["stats"]["sessions"], 0)
        miss, _ = kt.analyze({"sessions": self.sroot}, kt.ks.parse_since("2026-09-01"), root=self.root,
                             owners=self.owners, cwd_match=["/nowhere"])
        self.assertEqual(miss["stats"]["sessions"], 0)


WF = "99999999-0000-0000-0000-000000000000"


class BackendMiss(unittest.TestCase):
    @staticmethod
    def turns(*reads_writes, events_at=None, models=None):
        events_at, models = events_at or {}, models or {}
        return [{"input": 0, "cr": cr, "cw": cw, "events": events_at.get(i, []), "model": models.get(i, "m1")}
                for i, (cr, cw) in enumerate(reads_writes)]

    def test_later_read_of_an_older_entry_proves_it(self):
        t = self.turns((0, 2000), (2000, 1500), (0, 4000), (3500, 500))
        self.assertTrue(kt.backend_miss(t, 2, prev_ctx=3500))

    def test_read_inside_the_tools_and_system_prompt_proves_nothing(self):
        t = self.turns((0, 2000), (2000, 1500), (0, 4000), (2000, 2000))
        self.assertFalse(kt.backend_miss(t, 2, prev_ctx=3500))

    def test_reading_only_the_new_write_proves_nothing(self):
        t = self.turns((0, 2000), (2000, 1500), (0, 4000), (4000, 500))
        self.assertFalse(kt.backend_miss(t, 2, prev_ctx=3500))

    def test_an_event_ends_the_search(self):
        t = self.turns((0, 2000), (2000, 1500), (0, 4000), (0, 4000), (3500, 500), events_at={3: ["compaction"]})
        self.assertFalse(kt.backend_miss(t, 2, prev_ctx=3500))

    def test_system_prompt_change_raises_the_floor(self):
        t = self.turns((0, 2000), (0, 3000), (3000, 1000), (0, 5000), (3000, 2000),
                       events_at={1: ["system prompt change"]})
        self.assertFalse(kt.backend_miss(t, 3, prev_ctx=4000))

    def test_floor_skips_a_failed_first_request(self):
        t = self.turns((0, 0), (0, 2000), (2000, 1500), (0, 4000), (2000, 2500))
        self.assertFalse(kt.backend_miss(t, 3, prev_ctx=3500))

    def test_a_shrinking_context_after_the_miss_ends_the_search(self):
        t = self.turns((0, 2000), (2000, 1500), (0, 4000), (0, 3000), (3500, 500))
        self.assertFalse(kt.backend_miss(t, 2, prev_ctx=3500))

    def test_a_read_of_the_misses_own_write_proves_nothing(self):
        t = self.turns((0, 2000), (2000, 1500), (0, 3500), (3500, 500))
        self.assertFalse(kt.backend_miss(t, 2, prev_ctx=3500))

    def branch_events(self, parent_of_second_user):
        b = Builder().user("u").turn(usage(inp=5, cw=3000)).user("again").turn(usage(inp=5, cw=3000))
        for k, line in enumerate(b.lines):
            line["id"], line["parentId"] = f"e{k}", f"e{k - 1}" if k > 1 else None
        b.lines[3]["parentId"] = parent_of_second_user
        with tempfile.TemporaryDirectory() as d:
            b.write(os.path.join(d, "s.jsonl"))
            s = kt.read_session(os.path.join(d, "s.jsonl"), kt.ks.parse_since("2026-09-01"), [])
        return s

    def test_a_parent_break_is_a_branch(self):
        s = self.branch_events("e1")
        self.assertEqual([t["events"] for t in s["turns"]], [[], ["branch"]])
        self.assertEqual(kt.rewrite_cause(*s["turns"]), "branch")

    def test_a_reset_to_a_new_root_is_a_branch(self):
        self.assertEqual([t["events"] for t in self.branch_events(None)["turns"]], [[], ["branch"]])

    def test_a_linear_chain_has_no_branch(self):
        self.assertEqual([t["events"] for t in self.branch_events("e2")["turns"]], [[], []])

    def test_model_change_resets_the_floor(self):
        t = self.turns((0, 2000), (0, 4000), (0, 5000), (3000, 2500), models={1: "m2", 2: "m2", 3: "m2"})
        self.assertFalse(kt.backend_miss(t, 2, prev_ctx=4000))

    def test_report_splits_proven_misses_from_unexplained(self):
        with tempfile.TemporaryDirectory() as d:
            root = fake_root(d)
            for name, after in (("proven", 3505), ("unproven", 3000)):
                b = Builder().system(sections(root), TOOLS).user("u")
                b.turn(usage(inp=5, cw=3000)).turn(usage(inp=5, cr=3000, cw=500))
                b.turn(usage(inp=5, cw=4000, cost_cw=0.04)).turn(usage(inp=5, cr=after, cw=1500))
                b.write(os.path.join(d, "sessions", "proj", f"{name}.jsonl"))
            rep, _ = kt.analyze({"sessions": os.path.join(d, "sessions")}, kt.ks.parse_since("2026-09-01"),
                                min_sessions=1, top=1, root=root, owners=kt.Owners(root, rules=[]))
        causes = {r["cause"]: (r["turns"], r["cost"]) for r in rep["cache writes"]}
        self.assertEqual(causes["backend cache miss"], (1, 0.04))
        self.assertEqual(causes["unexplained"], (1, 0.04))
        self.assertEqual([r["owner"] for r in rep["upstream"]], ["upstream:provider routing"])


def child_id(n):
    return "00000000-0000-0000-0000-%012d" % n


def child(agent, n, model="m1", thinking="high", verdict=None, findings=()):
    b = Builder().system({"preamble": f'<active_agent name="{agent}"/>'}, TOOLS[:1]).user("task")
    b.event("thinking_level_change", thinkingLevel=thinking)
    b.event("session_info", name=f"subagent-{agent}-{child_id(n)}-1")
    b.turn(usage(inp=5, cw=2500, cost_cw=1.0), model=model)
    if verdict:
        b.structured("so", {"verdict": verdict, "findings": list(findings)})
    return b


def blocking(origin=None):
    f = {"severity": "blocking", "file": "a.go", "claim": "c", "evidence": "e"}
    if origin:
        f["origin"] = origin
    return f

class Loops(unittest.TestCase):
    """One review-loop run: round 1 has two reviewers, only the first blocks; round 2's second
    reviewer raises only a `new` finding, which does not block. Two other workflows, one with a
    `code-1` key among keys review-loop never uses, are not loops."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        cls.root = fake_root(d)
        sroot = os.path.join(d, "sessions")
        kids = {
            "code-1": child("coder", 1),
            "review-1-1": child("reviewer", 2, model="m1", verdict="blocked", findings=[blocking()]),
            "review-1-2": child("reviewer", 3, model="m2", verdict="ok"),
            "fix-2": child("coder", 4),
            "review-2-1": child("reviewer", 5, model="m1", verdict="ok"),
            "review-2-2": child("reviewer", 6, model="m2", verdict="blocked", findings=[blocking("new")]),
            "scan": child("explorer", 7),
            "other:code-1": child("coder", 8),
            "other:audit": child("worker", 9),
        }
        parent = main_session(cls.root)
        for n, (key, b) in enumerate(kids.items(), 1):
            wf = WF if key != "scan" else "88888888-0000-0000-0000-000000000000"
            if key.startswith("other:"):
                wf, key = "77777777-0000-0000-0000-000000000000", key[len("other:"):]
            b.write(os.path.join(sroot, "proj", "s0", child_id(n), "run-0", "session.jsonl"))
            parent.custom(f"Workflow child completed: **{key}**\nWorkflow run: {wf}\nChild run: {child_id(n)}\nOutput: x")
        parent.custom(f"Workflow child completed: **code-1**\nWorkflow run: {WF}\nChild run: {child_id(1)}\nOutput: x")
        parent.write(os.path.join(sroot, "proj", "s0.jsonl"))
        cls.report, _ = kt.analyze({"sessions": sroot}, kt.ks.parse_since("2026-09-01"), min_sessions=1, top=50,
                                   root=cls.root, owners=kt.Owners(cls.root, rules=[]))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_stats_and_shape(self):
        st = self.report["stats"]
        self.assertEqual((st["children"], st["mapped_children"], st["loops"]), (9, 9, 1))
        [loop] = self.report["loops"]
        self.assertEqual((loop["reviewers"], loop["rounds"], loop["runs"], loop["end"]), (2, 2, 1, {"clean": 1}))
        self.assertEqual(loop["coder_cost"], round(2 * (0.01 + 1.0), 2))
        self.assertEqual(loop["review_cost"], round(4 * (0.01 + 1.0) + 4 * (0.01 + 0.002), 2))

    def test_rounds_apply_the_downgrade(self):
        r1, r2 = self.report["loop rounds"]
        self.assertEqual((r1["round"], r1["reviews"], r1["rounds_with_blocker"], r1["blocking_by_origin"]),
                         (1, 2, 1, {"untagged": 1}))
        self.assertEqual((r2["round"], r2["rounds_with_blocker"], r2["blocking_by_origin"]), (2, 0, {}))

    def test_second_reviewer(self):
        [row] = self.report["second reviewer"]
        self.assertEqual((row["model"], row["rounds"], row["only_first"], row["only_second"], row["neither"]),
                         ("p/m2", 2, 1, 0, 1))

    def test_roles_carry_model_thinking_and_outcomes(self):
        rows = {(r["agent"], r["model"], r["thinking"]): r for r in self.report["roles"]}
        coder = rows[("coder", "p/m1", "high")]
        self.assertEqual((coder["sessions"], coder["first_rounds"], coder["first_round_clean"]), (3, 1, 0))
        r2 = rows[("reviewer", "p/m2", "high")]
        self.assertEqual((r2["reviews"], r2["reviews_blocked"]), (2, 1))
        self.assertIn(("explorer", "p/m1", "high"), rows)

    def test_missing_structured_result_is_unknown(self):
        self.assertIsNone(kt.effective_blocking(None, 1))
        self.assertEqual(kt.effective_blocking({"verdict": "blocked", "findings": [blocking("new")]}, 2), [])
        self.assertEqual(len(kt.effective_blocking({"verdict": "blocked", "findings": [blocking("prior")]}, 2)), 1)


class FirstSystem(unittest.TestCase):
    def test_non_object_lines_are_skipped(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "t.jsonl")
        sysmsg = {"type": "message", "message": {"role": "system", "sections": {"a": "b"}, "toolsAdded": [{"name": "t"}]}}
        with open(p, "w") as f:
            f.write("null\n[1]\n" + json.dumps(sysmsg) + "\n")
        self.assertEqual(kt.first_system(p), ({"a": "b"}, [{"name": "t"}]))


class Cli(unittest.TestCase):
    def test_upper_window_bound_excludes_later_turn_cost(self):
        with tempfile.TemporaryDirectory() as d:
            session = Builder().turn(usage(cost_cw=1)).turn(usage(cost_cw=9))
            session.write(os.path.join(d, 'session.jsonl'))
            report, _ = kt.analyze({'sessions': d}, kt.ks.to_dt('2026-10-01T00:00:00Z'),
                                   until=kt.ks.to_dt('2026-10-01T10:02:00Z'))
            all_rows = [r for r in report['totals'] if r['group'] == 'all']
            self.assertEqual(all_rows[0]['cost'], 1.01)

    def test_json_and_missing_source(self):
        with tempfile.TemporaryDirectory() as d:
            root = fake_root(d)
            main_session(root).write(os.path.join(d, "s", "p", "a.jsonl"))
            env = dict(os.environ, HWORKS_PI_SESSIONS=os.path.join(d, "s"), HWORKS_OWNER_MAP="")
            out = subprocess.run([sys.executable, SCRIPT, "--since", "2026-09-01", "--json", "--min-sessions", "1"],
                                 capture_output=True, text=True, env=env, check=True).stdout
            rows = [json.loads(line) for line in out.splitlines()]
            self.assertEqual(rows[0]["section"], "stats")
            self.assertIn("tool results", {r["section"] for r in rows})
            text = subprocess.run([sys.executable, SCRIPT, "--since", "2026-09-01", "--min-sessions", "1"],
                                  capture_output=True, text=True, env=env, check=True).stdout
            self.assertIn("== upstream ==  (flags only: nothing filed or drafted)", text)
            out = subprocess.run([sys.executable, SCRIPT, "--since", "2026-09-01", "--json", "--long-context", "5000"],
                                 capture_output=True, text=True, env=env, check=True).stdout
            [lc] = [json.loads(x) for x in out.splitlines() if '"group": "all"' in x and '"long context"' in x]
            self.assertEqual((lc["threshold"], lc["long_turns"]), (5000, 2))
            self.assertIn("long context sessions", {json.loads(x)["section"] for x in out.splitlines()})
            env["HWORKS_PI_SESSIONS"] = os.path.join(d, "absent")
            r = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True, env=env, check=True)
            self.assertIn("pi sessions: not found", r.stderr)


if __name__ == "__main__":
    unittest.main()
