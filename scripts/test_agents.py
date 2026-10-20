import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENTS = os.path.join(ROOT, "agents")


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line) if m else {}


def agent_files():
    return sorted(os.path.join(AGENTS, f) for f in os.listdir(AGENTS) if f.endswith(".md"))


class AgentSkillsTest(unittest.TestCase):
    # pi-subagents drops skills marked disable-model-invocation from a child's
    # skills: list without a warning, so a hidden skill there never reaches the child.
    def test_no_agent_lists_a_hidden_skill(self):
        for path in agent_files():
            with open(path) as f:
                listed = frontmatter(f.read()).get("skills", "")
            for name in filter(None, (s.strip() for s in listed.split(","))):
                skill = os.path.join(ROOT, "skills", name, "SKILL.md")
                self.assertTrue(os.path.exists(skill), f"{os.path.basename(path)}: skill {name} not found")
                with open(skill) as f:
                    hidden = frontmatter(f.read()).get("disable-model-invocation") == "true"
                self.assertFalse(hidden, f"{os.path.basename(path)} lists hidden skill {name}; name its path in the prompt")

    def test_every_hworks_path_in_an_agent_prompt_exists(self):
        for path in agent_files():
            with open(path) as f:
                text = f.read()
            for rel in re.findall(r"~/dev/hworks/([\w./-]+[\w/])", text):
                self.assertTrue(os.path.exists(os.path.join(ROOT, rel)), f"{os.path.basename(path)}: {rel} does not exist")

    def test_coder_reads_the_laziness_principle(self):
        with open(os.path.join(AGENTS, "coder.md")) as f:
            self.assertTrue("~/dev/hworks/skills/principle-laziness-protocol/SKILL.md" in f.read(), "coder.md must name the laziness principle")


if __name__ == "__main__":
    unittest.main()
