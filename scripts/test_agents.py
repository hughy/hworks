import importlib.util
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENTS = os.path.join(ROOT, "agents")

_spec = importlib.util.spec_from_file_location("kaizen_setup", os.path.join(ROOT, "scripts", "kaizen-setup.py"))
kaizen_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kaizen_setup)
frontmatter = kaizen_setup.agent_frontmatter


def agent_files():
    return sorted(os.path.join(AGENTS, f) for f in os.listdir(AGENTS) if f.endswith(".md"))


class AgentSkillsTest(unittest.TestCase):
    # pi-subagents drops skills marked disable-model-invocation from a child's
    # skills: list without a warning, so a hidden skill there never reaches the child.
    def test_no_agent_lists_a_hidden_skill(self):
        for path in agent_files():
            listed = frontmatter(path).get("skills", "")
            for name in (n for n in re.split(r"[,\s]+", listed) if n not in ("", "-")):
                skill = os.path.join(ROOT, "skills", name, "SKILL.md")
                self.assertTrue(os.path.exists(skill), f"{os.path.basename(path)}: skill {name} not found")
                hidden = frontmatter(skill).get("disable-model-invocation") == "true"
                self.assertFalse(hidden, f"{os.path.basename(path)} lists hidden skill {name}; name its path in the prompt")

    def test_every_hworks_path_in_an_agent_prompt_exists(self):
        for path in agent_files():
            with open(path) as f:
                text = f.read()
            for rel in re.findall(r"~/dev/hworks/([\w./-]+[\w/])", text):
                self.assertTrue(os.path.exists(os.path.join(ROOT, rel)), f"{os.path.basename(path)}: {rel} does not exist")

    def test_coder_names_the_laziness_principle(self):
        with open(os.path.join(AGENTS, "coder.md")) as f:
            self.assertTrue("~/dev/hworks/skills/principle-laziness-protocol/SKILL.md" in f.read(), "coder.md must name the laziness principle")


if __name__ == "__main__":
    unittest.main()
