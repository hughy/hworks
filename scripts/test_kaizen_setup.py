import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "kaizen-setup.py")

spec = importlib.util.spec_from_file_location("kaizen_setup", SCRIPT)
ksu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ksu)


def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path


def skill(root, name, desc="does a thing"):
    return write(os.path.join(root, name, "SKILL.md"), f"---\nname: {name}\ndescription: {desc}\n---\nbody\n")


def build(d, disable_builtins=True):
    """A fake home and hworks checkout with one of each kind of drift."""
    home = os.path.join(d, "home")
    pi = os.path.join(home, ".pi", "agent")
    root = os.path.join(d, "hworks")
    write(os.path.join(root, "scripts", "real.sh"))
    write(os.path.join(root, "extensions", "guard.ts"), "// Blocks risky shell commands before they run.\n")
    write(os.path.join(root, "agents", "coder.md"), "---\nname: coder\ndescription: writes code\n---\n")
    skill(os.path.join(root, "skills"), "own", "Summarize pull request review comments into a checklist")
    write(os.path.join(root, "skills", "own", "SKILL.md"),
          "---\nname: own\ndescription: Summarize pull request review comments into a checklist\n---\n"
          "See ../own/SKILL.md and ../missing/SKILL.md.\n")
    write(os.path.join(root, "global", "AGENTS.md"),
          "Run `scripts/real.sh` or `<hworks>/scripts/gone.sh --x`, then /skill:dup or /skill:nope. "
          "Read `skills/own/SKILL.md`, `agents/coder.md`, and `agents/ghost.md`. `node_modules/x/y` is foreign, `scripts/...` a placeholder.\n")

    extra = os.path.join(d, "extra-skills")
    skill(extra, "dup")
    skill(extra, "solo")
    skill(os.path.join(home, ".agents", "skills"), "dup")
    write(os.path.join(home, ".agents", ".skill-lock.json"),
          json.dumps({"version": 3, "skills": {"vendor/skills/dup": {"source": "x"}}}))

    pkg = os.path.join(d, "lib", "node", "v1.2.3", "pkg")
    write(os.path.join(pkg, "package.json"), json.dumps({"pi": {"extensions": []}}))
    write(os.path.join(pkg, "agents", "scout.md"), "---\nname: scout\ndescription: s\n---\n")
    write(os.path.join(pi, "agents", "team", "coder.md"), "---\nname: coder\ndescription: c\n---\n")
    settings = {
        "skills": [extra],
        "packages": [pkg],
        "extensions": ["-builtin:mcp", os.path.join(d, "gone", "ext.ts")],
        "theme": "dark",
        "subagents": {"disableBuiltins": disable_builtins,
                      "agentOverrides": {"coder": {}, "scout": {}, "ghost": {}}},
    }
    write(os.path.join(pi, "settings.json"), json.dumps(settings))
    write(os.path.join(pi, "settings.json.bak"), "{}")
    write(os.path.join(pi, "sessions", "old.bak"))

    ext = os.path.join(pi, "extensions")
    os.makedirs(ext)
    os.symlink(os.path.join(root, "extensions", "guard.ts"), os.path.join(ext, "guard.ts"))
    os.symlink(os.path.join(d, "nowhere.ts"), os.path.join(ext, "dead.ts"))
    write(os.path.join(ext, "mine.ts"))

    sroot = os.path.join(pi, "sessions")
    system = {"type": "message", "message": {"role": "system", "content": "", "sections": {
        "skills": "Skill locations below are relative to /base/;\n<skill><name>pr-digest</name><description>"
                  "Summarize pull request review comments into a checklist for the author</description>"
                  "<location>/opt/node_modules/@acme/agent/skills/pr-digest/SKILL.md</location></skill>"},
        "toolsAdded": [{"name": "shell_guard", "description": "Blocks risky shell commands"},
                       {"name": "weather", "description": "Forecast for a city"}]}}
    write(os.path.join(sroot, "proj", "a.jsonl"),
          json.dumps({"type": "session", "cwd": "/w"}) + "\n" + json.dumps(system) + "\n")
    return home, root, sroot


class Audit(unittest.TestCase):
    def run_audit(self, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home, root, sroot = build(tmp.name, **kw)
        self.d, self.root = tmp.name, root
        owners = ksu.kt.Owners(root, rules=[])
        return ksu.analyze(home, ksu.ks.parse_since("2000-01-01"), root=root, sroot=sroot, owners=owners)

    def rows(self, report, section, **match):
        return [r for r in report[section] if all(r.get(k) == v for k, v in match.items())]

    def test_duplicate_skill_across_roots(self):
        rep, _ = self.run_audit()
        [dup] = rep["duplicates"]
        self.assertEqual(dup["name"], "dup")
        self.assertEqual(len(dup["roots"]), 2)
        self.assertFalse(dup["same_file"])
        locked = {r["root"].endswith(".agents/skills"): r["lock_managed"] for r in self.rows(rep, "skills", name="dup")}
        self.assertEqual(locked, {True: True, False: False})
        self.assertEqual(self.rows(rep, "skills", name="solo")[0]["description_chars"], len("does a thing"))

    def test_missing_and_version_pinned_paths(self):
        rep, _ = self.run_audit()
        missing = self.rows(rep, "settings", issue="missing path")
        self.assertEqual([r["key"] for r in missing], ["extensions[1]"])
        self.assertEqual(missing[0]["owner"], "local")
        pinned = self.rows(rep, "settings", issue="version-pinned path")
        self.assertEqual([(r["key"], r["segment"]) for r in pinned], [("packages[0]", "v1.2.3")])

    def test_override_naming_missing_agent(self):
        rep, _ = self.run_audit(disable_builtins=True)
        self.assertEqual([r["key"] for r in self.rows(rep, "settings", issue="stale override")],
                         ["subagents.agentOverrides.ghost"])
        self.assertEqual(self.rows(rep, "settings", issue="may be a builtin"), [])
        rep, _ = self.run_audit(disable_builtins=False)
        self.assertEqual(self.rows(rep, "settings", issue="stale override"), [])
        self.assertEqual([r["key"] for r in self.rows(rep, "settings", issue="may be a builtin")],
                         ["subagents.agentOverrides.ghost"])

    def test_extensions_and_broken_link(self):
        rep, _ = self.run_audit()
        ext = {r["name"]: r for r in rep["extensions"]}
        self.assertEqual((ext["dead.ts"]["kind"], ext["dead.ts"]["broken"]), ("broken link", True))
        self.assertEqual((ext["guard.ts"]["kind"], ext["guard.ts"]["owner"]), ("link", "hworks"))
        self.assertEqual((ext["mine.ts"]["kind"], ext["mine.ts"]["owner"]), ("file", "local"))

    def test_leftovers_skip_sessions(self):
        rep, _ = self.run_audit()
        self.assertEqual([os.path.basename(r["path"]) for r in rep["leftovers"]], ["settings.json.bak"])
        self.assertRegex(rep["leftovers"][0]["mtime"], r"^\d{4}-\d\d-\d\d$")

    def test_stale_and_valid_refs(self):
        rep, _ = self.run_audit()
        stale = {(r["file"], r["ref"]) for r in rep["stale refs"]}
        self.assertEqual(stale, {("global/AGENTS.md", "scripts/gone.sh"), ("global/AGENTS.md", "/skill:nope"),
                                 ("global/AGENTS.md", "agents/ghost.md"),
                                 ("skills/own/SKILL.md", "../missing/SKILL.md")})
        self.assertTrue(all(r["owner"] == "hworks" for r in rep["stale refs"]))

    def test_overlap_from_session_baseline(self):
        rep, _ = self.run_audit()
        by = {(r["kind"], r["name"]): r for r in rep["overlap"]}
        own = by[("skill", "own")]["candidates"][0]
        self.assertEqual((own["kind"], own["name"], own["owner"]), ("skill", "pr-digest", "upstream:@acme/agent"))
        self.assertGreater(own["score"], 0.5)
        guard = by[("extension", "guard")]["candidates"][0]
        self.assertEqual((guard["kind"], guard["name"]), ("tool", "shell_guard"))
        self.assertNotIn("weather", {c["name"] for r in rep["overlap"] for c in r["candidates"]})

    def test_missing_sources_are_notes(self):
        with tempfile.TemporaryDirectory() as d:
            root = os.path.join(d, "hworks")
            os.makedirs(root)
            rep, notes = ksu.analyze(os.path.join(d, "nohome"), ksu.ks.parse_since("7d"), root=root,
                                     sroot=os.path.join(d, "nosessions"), owners=ksu.kt.Owners(root, rules=[]))
        text = "\n".join(notes)
        for want in ("pi settings: not found", "skill lock: not found", "extensions: not found",
                     "pi sessions: not found"):
            self.assertIn(want, text)
        self.assertEqual(rep["skills"], [])


class Cli(unittest.TestCase):
    def test_json_and_text(self):
        with tempfile.TemporaryDirectory() as d:
            home, _root, sroot = build(d)
            env = dict(os.environ, HOME=home, HWORKS_PI_SESSIONS=sroot, HWORKS_OWNER_MAP="")
            out = subprocess.run([sys.executable, SCRIPT, "--json", "--since", "2000-01-01"], capture_output=True,
                                 text=True, env=env, check=True).stdout
            rows = [json.loads(x) for x in out.splitlines()]
            self.assertEqual(rows[0]["section"], "stats")
            self.assertIn("ghost", {r.get("key", "").rsplit(".", 1)[-1] for r in rows if r["section"] == "settings"})
            self.assertTrue(all("owner" in r for r in rows if r["section"] not in ("stats", "note")))
            text = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True, env=env, check=True).stdout
            self.assertIn("== duplicates ==", text)
            self.assertIn("dead.ts", text)
            env["HOME"] = os.path.join(d, "absent")
            env["HWORKS_PI_SESSIONS"] = os.path.join(d, "absent", "s")
            r = subprocess.run([sys.executable, SCRIPT, "--json"], capture_output=True, text=True, env=env, check=True)
            self.assertIn("pi settings: not found", r.stdout)


if __name__ == "__main__":
    unittest.main()
