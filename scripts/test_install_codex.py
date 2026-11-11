import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class InstallCodexTest(unittest.TestCase):
    def test_install_check_and_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            clone = home / "dev/hworks"
            shared = clone / "pstack/skills/example"
            shared.mkdir(parents=True)
            (shared / "SKILL.md").write_text("---\nname: example\ndescription: Example\n---\n")
            (shared / "reference.md").write_text("Reference")
            (clone / "skills").mkdir()
            (clone / "skills/example").symlink_to("../pstack/skills/example")
            (clone / "global").mkdir()
            (clone / "global/AGENTS.md").write_text("Guidance")
            (clone / "scripts").mkdir()
            script = clone / "scripts/install.sh"
            shutil.copy2(Path(__file__).with_name("install.sh"), script)
            codex = home / "custom-codex"
            tasks = home / "tasks"
            env = dict(os.environ, HOME=str(home), CODEX_HOME=str(codex),
                       HWORKS_TASKS_DIR=str(tasks))

            def run(expected, *args):
                result = subprocess.run(
                    ["bash", script, "--codex", *args], cwd=home, env=env,
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                return result.stdout

            run(1, "--check")
            self.assertFalse((home / ".agents").exists())
            self.assertFalse(codex.exists())
            run(0)
            run(0)
            run(0, "--check")
            self.assertEqual((codex / "AGENTS.md").resolve(), clone / "global/AGENTS.md")
            self.assertTrue(tasks.is_dir())
            self.assertFalse((home / ".pi").exists())
            self.assertFalse((home / ".claude").exists())
            skill = home / ".agents/skills/example"
            self.assertEqual((skill / "SKILL.md").resolve(), shared / "SKILL.md")
            self.assertEqual((skill / "reference.md").read_text(), "Reference")

            skill.unlink()
            skill.symlink_to(home / "other")
            self.assertIn("differs", run(1))
            self.assertEqual(skill.readlink(), home / "other")
