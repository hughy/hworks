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


RACE_PRELUDE = """
import os
_armed = [False]
def _swap_after(fn):
    def wrapper(*a, **k):
        r = fn(*a, **k)
        if _armed[0]:
            _armed[0] = False
            frames = os.environ["RACE_DIR"]
            os.rename(frames, frames + ".real")
            os.symlink(os.environ["RACE_TARGET"], frames)
        return r
    return wrapper
os.path.realpath = _swap_after(os.path.realpath)
os.open = _swap_after(os.open)
"""

RACE_WRAPPER = """
_real_delete = delete
def delete(path, kind, unit):
    full = os.path.join(os.environ["PRUNE_ROOT"], path)
    _armed[0] = full == os.path.join(os.environ["RACE_DIR"], "big.bin")
    return _real_delete(path, kind, unit)
"""

ROOT_SWAP_WRAPPER = """
_real_delete = delete
_swapped = [False]
def delete(path, kind, unit):
    if not _swapped[0]:
        _swapped[0] = True
        parent = os.environ["SWAP_PARENT"]
        os.rename(parent, parent + ".real")
        os.symlink(os.environ["SWAP_TARGET"], parent)
    return _real_delete(path, kind, unit)
"""

TASK_AFTER_SCAN_WRAPPER = """
_real_candidates = candidates
def candidates(unit, unit_fd):
    found = _real_candidates(unit, unit_fd)
    for path, _, kind in found:
        if os.path.basename(path) == "build-cache":
            open(os.path.join(os.environ["PRUNE_ROOT"], path, ".task"), "w").close()
    return found
"""

TASK_AFTER_RESCAN_WRAPPER = """
_real_bulk_scan = bulk_scan
_scans = {}
def bulk_scan(top, dir_fd):
    r = _real_bulk_scan(top, dir_fd)
    _scans[top] = _scans.get(top, 0) + 1
    if top == "build-cache" and _scans[top] == 2:
        open(os.path.join(os.environ["TASK_DIR_HOOK"], ".task"), "w").close()
    return r
"""


def embedded_python():
    with open(SCRIPT) as f:
        src = f.read()
    return src.split("<<'PY'\n", 1)[1].rsplit("\nPY\n", 1)[0]


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

    def test_unreadable_subdir_keeps_unit_active(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores dir permissions")
        private = os.path.join(self.root, "legacy", "private")
        write(os.path.join(private, "fresh.md"), old=False)
        os.chmod(private, 0)
        try:
            out = self.run_prune("--json", "--apply")
        finally:
            os.chmod(private, 0o755)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("treating it as active", out.stderr)
        self.assertTrue(self.exists("legacy_big"))
        self.assertEqual(json.loads(out.stdout)["active_units"], 2)

    def test_dir_swapped_for_symlink_before_delete_is_not_followed(self):
        frames = os.path.dirname(self.files["idle_big"])
        target = os.path.join(self.outside, "frames")
        write(os.path.join(target, "big.bin"), BIG)
        src = embedded_python().replace("\nreport = {", RACE_WRAPPER + "\nreport = {", 1)
        env = dict(os.environ, PRUNE_ROOT=self.root, PRUNE_OLDER="14d", PRUNE_APPLY="1",
                   PRUNE_JSON="1", RACE_DIR=frames, RACE_TARGET=target)
        out = subprocess.run(["python3", "-c", RACE_PRELUDE + src], capture_output=True,
                             text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(os.path.islink(frames), "race hook did not run")
        self.assertTrue(os.path.exists(os.path.join(target, "big.bin")))
        self.assertTrue(os.path.exists(os.path.join(frames + ".real", "big.bin")))
        rep = json.loads(out.stdout)
        self.assertEqual(rep["freed_bytes"], rep["reclaimable_bytes"] - BIG)

    def test_root_ancestor_swapped_for_symlink_before_delete_is_not_followed(self):
        parent = os.path.join(self.base, "p")
        root = os.path.join(parent, "root")
        evil = os.path.join(self.base, "evil")
        write(os.path.join(root, "legacy", "big.bin"), BIG)
        write(os.path.join(evil, "root", "legacy", "big.bin"), BIG)
        src = embedded_python().replace("\nreport = {", ROOT_SWAP_WRAPPER + "\nreport = {", 1)
        env = dict(os.environ, PRUNE_ROOT=root, PRUNE_OLDER="14d", PRUNE_APPLY="1",
                   PRUNE_JSON="1", SWAP_PARENT=parent, SWAP_TARGET=evil)
        out = subprocess.run(["python3", "-c", src], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(os.path.islink(parent), "swap hook did not run")
        self.assertTrue(os.path.exists(os.path.join(evil, "root", "legacy", "big.bin")))
        self.assertFalse(os.path.exists(os.path.join(parent + ".real", "root", "legacy", "big.bin")))
        self.assertEqual(json.loads(out.stdout)["freed_bytes"], BIG)

    def test_apply_runs_on_python_3_9(self):
        py = "/usr/bin/python3"
        if not os.access(py, os.X_OK):
            self.skipTest("no system python3")
        ver = subprocess.run([py, "-c", "import sys; print(sys.version_info[:2] < (3, 11))"],
                             capture_output=True, text=True)
        if ver.stdout.strip() != "True":
            self.skipTest("system python3 is 3.11 or newer")
        out = self.run_prune("--json", "--apply", env_extra={"PATH": "/usr/bin:/bin"})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(self.exists("idle_nm"))
        self.assertTrue(self.exists("idle_md"))
        rep = json.loads(out.stdout)
        self.assertEqual(rep["freed_bytes"], rep["reclaimable_bytes"])

    def test_bulk_named_dir_in_orchestrate_store_kept(self):
        store = os.path.join(self.idle, "orchestrate", "prog", "outputs", "cache")
        note = os.path.join(store, "cache-r1-coder.md")
        write(note, BIG)
        write(os.path.join(store, "node_modules", "x.js"))
        rep = self.report("--apply")
        self.assertTrue(os.path.exists(note))
        self.assertTrue(os.path.exists(os.path.join(store, "node_modules", "x.js")))
        self.assertFalse(any("orchestrate" in c["path"] for c in rep["candidates"]))

    def test_bulk_named_dir_holding_task_file_kept(self):
        task = os.path.join(self.idle, "build-cache", "inner", ".task")
        dep = os.path.join(self.idle, "build-cache", "inner", "node_modules", "x.js")
        big = os.path.join(self.idle, "build-cache", "big.bin")
        write(task)
        write(dep)
        write(big, BIG)
        self.report("--apply")
        self.assertTrue(os.path.exists(task))
        self.assertFalse(os.path.exists(dep))
        self.assertFalse(os.path.exists(big))

    def run_hooked(self, wrapper, **env_extra):
        src = embedded_python().replace("\nreport = {", wrapper + "\nreport = {", 1)
        env = dict(os.environ, PRUNE_ROOT=self.root, PRUNE_OLDER="14d", PRUNE_APPLY="1",
                   PRUNE_JSON="1", **env_extra)
        out = subprocess.run(["python3", "-c", src], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_task_file_created_after_scan_kept_on_apply(self):
        cache = os.path.join(self.idle, "build-cache")
        write(os.path.join(cache, "old.bin"), 1024)
        rep = self.run_hooked(TASK_AFTER_SCAN_WRAPPER)
        self.assertTrue(os.path.exists(os.path.join(cache, ".task")))
        self.assertTrue(os.path.exists(os.path.join(cache, "old.bin")))
        self.assertIn(os.path.relpath(cache, self.root), [c["path"] for c in rep["candidates"]])
        self.assertEqual(rep["freed_bytes"], rep["reclaimable_bytes"] - 1024)

    def test_rmtree_never_unlinks_task_file(self):
        inner = os.path.join(self.idle, "build-cache", "inner")
        write(os.path.join(inner, "old.bin"), 1024)
        rep = self.run_hooked(TASK_AFTER_RESCAN_WRAPPER, TASK_DIR_HOOK=inner)
        self.assertTrue(os.path.exists(os.path.join(inner, ".task")))
        self.assertFalse(os.path.exists(os.path.join(inner, "old.bin")))
        self.assertEqual(rep["freed_bytes"], rep["reclaimable_bytes"] - 1024)

    def test_stray_double_dash_dir_is_one_unit(self):
        stray = os.path.join(self.root, "old--clone")
        write(os.path.join(stray, "a", "fresh.md"), old=False)
        write(os.path.join(stray, "b", "big.bin"), BIG)
        rep = self.report("--apply")
        self.assertTrue(os.path.exists(os.path.join(stray, "b", "big.bin")))
        self.assertFalse(any(c["path"].startswith("old--clone/") for c in rep["candidates"]))
        self.assertEqual(rep["active_units"], 2)

    def test_stray_double_dash_dir_with_only_files_classified(self):
        write(os.path.join(self.root, "empty--stray", "big.bin"), BIG)
        rep = self.report()
        self.assertIn("empty--stray/big.bin", {c["path"] for c in rep["candidates"]})
        self.assertEqual(rep["idle_units"], 4)

    def test_files_directly_in_repo_and_branch_dirs_classified(self):
        repo = os.path.join(self.root, "github.com--o--r")
        write(os.path.join(repo, "big.bin"), BIG)
        write(os.path.join(repo, "main", "big.bin"), BIG)
        write(os.path.join(repo, "main", "keep.md"), BIG)
        rep = self.report("--apply")
        paths = {c["path"] for c in rep["candidates"]}
        self.assertIn("github.com--o--r/big.bin", paths)
        self.assertIn("github.com--o--r/main/big.bin", paths)
        self.assertTrue(os.path.exists(os.path.join(repo, "main", "keep.md")))
        self.assertTrue(os.path.isdir(self.idle))
        self.assertEqual(rep["idle_units"], 5)

    def test_summary_line_names_idle_threshold(self):
        out = self.run_prune()
        self.assertIn("units: 3 idle (no file newer than 14d), 1 active", out.stdout)

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
