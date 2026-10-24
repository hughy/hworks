import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONF = """p coder model-a
p babysitter model-b
p review2 model-c
"""


class ModelsTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        os.makedirs(os.path.join(self.root, "scripts"))
        os.makedirs(os.path.join(self.root, "agents"))
        os.makedirs(os.path.join(self.root, "adapters", "local"))
        shutil.copy(os.path.join(ROOT, "scripts", "models.sh"), os.path.join(self.root, "scripts"))
        open(os.path.join(self.root, "agents", "coder.md"), "w").close()
        with open(os.path.join(self.root, "models.conf"), "w") as f:
            f.write(CONF)
        self.settings = os.path.join(self.root, "settings.json")
        with open(self.settings, "w") as f:
            json.dump({"subagents": {"agentOverrides": {"babysitter": {"tools": ["read"]}}}}, f)

    def run_models(self, *args, env=None):
        e = {k: v for k, v in os.environ.items() if k != "HWORKS_MODEL_AGENTS"}
        e["PI_SETTINGS"] = self.settings
        e.update(env or {})
        return subprocess.run(["bash", os.path.join(self.root, "scripts", "models.sh"), *args],
                              env=e, capture_output=True, text=True, check=True).stdout

    def overrides(self):
        with open(self.settings) as f:
            return json.load(f)["subagents"]["agentOverrides"]

    def write_env(self, text):
        with open(os.path.join(self.root, "adapters", "local", "models.env"), "w") as f:
            f.write(text)

    def test_role_without_agent_file_is_a_slot(self):
        out = self.run_models("p")
        o = self.overrides()
        self.assertEqual(o["coder"]["model"], "model-a")
        self.assertNotIn("model", o["babysitter"])
        self.assertNotIn("review2", o)
        self.assertIn("babysitter   model-b (slot)", out)

    def test_env_file_names_an_external_agent(self):
        self.write_env('HWORKS_MODEL_AGENTS="babysitter, other"\n')
        out = self.run_models("p")
        o = self.overrides()
        self.assertEqual(o["babysitter"], {"tools": ["read"], "model": "model-b"})
        self.assertNotIn("review2", o)
        self.assertIn("babysitter   model-b\n", out)
        self.assertIn("review2      model-c (slot)", out)

    def test_environment_wins_over_env_file(self):
        self.write_env("HWORKS_MODEL_AGENTS=babysitter\n")
        self.run_models("p", env={"HWORKS_MODEL_AGENTS": ""})
        self.assertNotIn("model", self.overrides()["babysitter"])


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


class WorktreeTest(unittest.TestCase):
    def test_linked_worktree_reads_main_checkout_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            main, wt = linked_worktree(tmp)
            os.makedirs(os.path.join(wt, "scripts"))
            os.makedirs(os.path.join(wt, "agents"))
            shutil.copy(os.path.join(ROOT, "scripts", "models.sh"), os.path.join(wt, "scripts"))
            with open(os.path.join(wt, "models.conf"), "w") as f:
                f.write(CONF)
            with open(os.path.join(main, "adapters", "local", "models.env"), "w") as f:
                f.write("HWORKS_MODEL_AGENTS=babysitter\n")
            settings = os.path.join(tmp, "settings.json")
            with open(settings, "w") as f:
                json.dump({}, f)
            e = {k: v for k, v in os.environ.items() if k != "HWORKS_MODEL_AGENTS" and not k.startswith("GIT_")}
            e["PI_SETTINGS"] = settings
            subprocess.run(["bash", os.path.join(wt, "scripts", "models.sh"), "p"], env=e, check=True, capture_output=True)
            with open(settings) as f:
                self.assertEqual(json.load(f)["subagents"]["agentOverrides"]["babysitter"]["model"], "model-b")


if __name__ == "__main__":
    unittest.main()
