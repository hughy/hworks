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


if __name__ == "__main__":
    unittest.main()
