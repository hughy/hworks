import json
import os
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "task-prune.sh")
OLD = time.time() - 30 * 86400
BIG = (1 << 20) + 1


def write(path, size=10, old=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    if old:
        os.utime(path, (OLD, OLD))


class TaskPrune(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.realpath(self.tmp.name)
        self.root = os.path.join(self.base, "tasks")
        self.outside = os.path.join(self.base, "outside")
        os.makedirs(self.root)
        self.idle = os.path.join(self.root, "github.com--o--r", "main", "idle")
        self.active = os.path.join(self.root, "github.com--o--r", "main", "active")
        r = self.root
        self.files = {
            "idle_md": os.path.join(self.idle, "progress.md"),
            "idle_big": os.path.join(self.idle, "frames", "big.bin"),
            "idle_small": os.path.join(self.idle, "small.txt"),
            "idle_deep_md": os.path.join(self.idle, "a", "b", "big.md"),
            "idle_deep_jsonl": os.path.join(self.idle, "a", "b", "log.jsonl"),
            "idle_deep_task": os.path.join(self.idle, "a", "b", ".task"),
            "idle_deep_small": os.path.join(self.idle, "a", "b", "note.txt"),
            "idle_git": os.path.join(self.idle, "clone", ".git", "objects", "pack"),
            "idle_nm": os.path.join(self.idle, "clone", "node_modules", "x", "index.js"),
            "idle_cache": os.path.join(self.idle, "Linux-Go-Cache", "x"),
            "active_old_big": os.path.join(self.active, "big.bin"),
            "active_nm": os.path.join(self.active, "node_modules", "x.js"),
            "active_fresh": os.path.join(self.active, "notes.md"),
            "root_file": os.path.join(r, "blockers.jsonl"),
            "root_big": os.path.join(r, "big.bin"),
            "misc_big": os.path.join(r, "_misc", "m", "big.bin"),
            "legacy_big": os.path.join(r, "legacy", "sub", "big.bin"),
            "legacy_md": os.path.join(r, "legacy", "notes.md"),
            "outside_big": os.path.join(self.outside, "node_modules", "big.bin"),
        }
        big = {"idle_big", "idle_deep_md", "idle_deep_jsonl", "idle_deep_task", "idle_git",
               "active_old_big", "root_big", "misc_big", "legacy_big", "outside_big"}
        for k, p in self.files.items():
            write(p, BIG if k in big else 10, old=k != "active_fresh")
        os.symlink(self.outside, os.path.join(self.idle, "link"))
        os.symlink(os.path.join(self.outside, "node_modules"), os.path.join(self.idle, "node_modules"))

    def tearDown(self):
        self.tmp.cleanup()

    def run_prune(self, *args, root=None, env_extra=None):
        env = dict(os.environ, HWORKS_TASKS_DIR=self.root if root is None else root)
        env.update(env_extra or {})
        return subprocess.run([SCRIPT, *args], capture_output=True, text=True, env=env)

    def report(self, *args):
        out = self.run_prune("--json", *args)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def exists(self, key):
        return os.path.lexists(self.files[key])

    def test_dry_run_deletes_nothing(self):
        rep = self.report()
        for k in self.files:
            self.assertTrue(self.exists(k), k)
        paths = {c["path"] for c in rep["candidates"]}
        self.assertIn("github.com--o--r/main/idle/frames/big.bin", paths)
        self.assertIn("github.com--o--r/main/idle/clone/.git", paths)
        self.assertGreater(rep["reclaimable_bytes"], 4 * (1 << 20))
        self.assertNotIn("freed_bytes", rep)
        text = self.run_prune()
        self.assertIn("reclaimable:", text.stdout)
        self.assertIn("idle", text.stdout)
        for k in self.files:
            self.assertTrue(self.exists(k), k)

    def test_apply_removes_bulk_in_idle_units_only(self):
        rep = self.report("--apply")
        for k in ("idle_big", "idle_git", "idle_nm", "idle_cache", "misc_big", "legacy_big"):
            self.assertFalse(self.exists(k), k)
        self.assertFalse(os.path.exists(os.path.join(self.idle, "clone", ".git")))
        self.assertFalse(os.path.exists(os.path.join(self.idle, "Linux-Go-Cache")))
        for k in ("idle_md", "idle_small", "idle_deep_md", "idle_deep_jsonl", "idle_deep_task",
                  "idle_deep_small", "legacy_md", "active_old_big", "active_nm", "active_fresh",
                  "root_file", "root_big", "outside_big"):
            self.assertTrue(self.exists(k), k)
        self.assertEqual(rep["freed_bytes"], rep["reclaimable_bytes"])
        self.assertEqual(rep["active_units"], 1)
        self.assertEqual(rep["idle_units"], 3)

    def test_symlinks_not_traversed(self):
        rep = self.report("--apply")
        self.assertFalse(any("link" in c["path"] for c in rep["candidates"]))
        self.assertFalse(any(c["path"].endswith("idle/node_modules") for c in rep["candidates"]))
        self.assertTrue(os.path.islink(os.path.join(self.idle, "link")))
        self.assertTrue(os.path.islink(os.path.join(self.idle, "node_modules")))
        self.assertTrue(self.exists("outside_big"))

    def test_legacy_top_level_dir_is_one_unit(self):
        legacy = os.path.join(self.root, "legacy")
        write(os.path.join(legacy, "deep", "fresh.txt"), old=False)
        rep = self.report("--apply")
        self.assertTrue(self.exists("legacy_big"))
        self.assertFalse(any(c["path"].startswith("legacy/") for c in rep["candidates"]))

    def test_empty_dirs_removed_unit_kept(self):
        unit = os.path.join(self.root, "_misc", "m")
        self.report("--apply")
        self.assertFalse(os.path.exists(os.path.join(self.idle, "frames")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "legacy", "sub")))
        self.assertFalse(os.path.exists(os.path.join(self.idle, "clone")))
        self.assertTrue(os.path.isdir(unit))
        self.assertEqual(os.listdir(unit), [])

    def test_older_than_controls_idleness(self):
        rep = self.report("--older-than", "60d", "--apply")
        self.assertEqual(rep["idle_units"], 0)
        self.assertEqual(rep["candidates"], [])
        self.assertTrue(self.exists("idle_big"))

    def test_unsafe_roots_refused(self):
        home = os.path.join(self.base, "home")
        os.makedirs(home)
        write(os.path.join(home, "x", "big.bin"), BIG)
        for root, extra in (("/", {}), (home, {"HOME": home}),
                            (os.path.join(self.base, "missing"), {})):
            out = self.run_prune("--apply", root=root, env_extra=extra)
            self.assertEqual(out.returncode, 2, root)
            self.assertIn("refusing", out.stderr)
        self.assertTrue(os.path.exists(os.path.join(home, "x", "big.bin")))


if __name__ == "__main__":
    unittest.main()
