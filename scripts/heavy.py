#!/usr/bin/env python3
"""Run a CPU-heavy command (a gate, a test suite, a linter) under a host-wide slot lock.

usage: heavy.py COMMAND [ARGS...]

Parallel agents on one host each run their own gate, and concurrent compiles, race tests, and linters starve each
other until lint times out with 0 issues or timing-sensitive tests fail. This waits for one of
$HWORKS_HEAVY_SLOTS slots (default 1; 0 runs the command at once). A holder process in its own session owns the
slot: it runs COMMAND in a new process group, and after COMMAND exits it waits up to $HWORKS_HEAVY_DRAIN_S seconds
(default 30) for the rest of the group, then terminates what is left (SIGTERM, then SIGKILL) and confirms the group
is gone before it frees the slot. If heavy.py dies first, even by SIGKILL or a kill of its process group, the
holder ends COMMAND's group the same way, so a cancelled gate neither keeps running nor overlaps the next one. A
process that leaves COMMAND's group escapes this.

Slots are flock files under ${XDG_STATE_HOME:-~/.local/state}/hworks/heavy; the kernel frees one when its last
holder exits. A heavy.py run inside COMMAND runs its command directly, since an ancestor holds the slot.
Waiting counts toward any timeout around this command: it logs the wait and the holder on stderr, so a timeout
spent queueing reads as one. Exits with COMMAND's status, or 128 plus the signal that ended it.
Standard library only.
"""

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
import traceback

HELD = "HWORKS_HEAVY_HELD"
POLL_S = 1.0
FORWARD = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)


def log(msg):
    """Report on stderr; a reader that went away (a killed caller) must not stop cleanup."""
    try:
        print(f"heavy.py: {msg}", file=sys.stderr, flush=True)
    except OSError:
        pass


def lock_dir():
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state, "hworks", "heavy")


def env_int(name, default):
    raw = os.environ.get(name, "")
    if raw == "":
        return default
    if not raw.isdigit():
        sys.exit(f"heavy.py: {name} must be a non-negative integer, got: {raw}")
    return int(raw)


def holders(paths):
    out = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            pass
    return out


def acquire(slots):
    """Block until a slot is free; return its open file, which holds the lock until closed."""
    d = lock_dir()
    os.makedirs(d, exist_ok=True)
    paths = [os.path.join(d, f"slot-{i}.lock") for i in range(slots)]
    start, announced = time.monotonic(), False
    while True:
        for p in paths:
            f = open(p, "a+", encoding="utf-8")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                f.close()
                continue
            waited = time.monotonic() - start
            if announced:
                log(f"got a slot after {waited:.0f}s")
            return f
        if not announced:
            busy = "; ".join(f"pid {h.get('pid')} since {h.get('since')}: {h.get('cmd')}" for h in holders(paths))
            log(f"all {slots} slots busy, waiting ({busy or 'holders unknown'})")
            announced = True
        time.sleep(POLL_S)


def record(f, argv):
    f.seek(0)
    f.truncate()
    f.write(json.dumps({"pid": os.getpid(), "since": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "cwd": os.getcwd(), "cmd": " ".join(argv)[:300]}))
    f.flush()


def group_alive(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def hold(argv, drain_s, parent):
    """Run COMMAND and drain its group; end it early if heavy.py, our parent, has died."""
    os.setsid()
    try:
        proc = subprocess.Popen(argv, start_new_session=True, env={**os.environ, HELD: "1"})
    except OSError as e:
        log(f"cannot run {argv[0]}: {e}")
        return 127

    def forward(signum, _frame):
        try:
            os.killpg(proc.pid, signum)
        except ProcessLookupError:
            pass

    for s in FORWARD:
        signal.signal(s, forward)
    while proc.poll() is None:
        if os.getppid() != parent:
            terminate(proc.pid)
            log("exited before its command; ended the command")
            break
        time.sleep(0.2)
    rc = proc.wait()
    drain(proc.pid, drain_s)
    return rc if rc >= 0 else 128 - rc


def run(argv, drain_s):
    parent = os.getpid()
    sys.stdout.flush()
    sys.stderr.flush()
    pid = os.fork()
    if pid == 0:
        code = 1
        try:
            code = hold(argv, drain_s, parent)
        except BaseException:  # noqa: BLE001 - the holder must still exit, never return into main
            traceback.print_exc()
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(code)

    def forward(signum, _frame):
        try:
            os.kill(pid, signum)
        except ProcessLookupError:
            pass

    for s in FORWARD:
        signal.signal(s, forward)
    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    return code if code >= 0 else 128 - code


def wait_gone(pgid, seconds):
    deadline = time.monotonic() + seconds
    while group_alive(pgid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)
    return True


def drain(pgid, drain_s):
    if wait_gone(pgid, drain_s):
        return
    log(f"process group {pgid} still running {drain_s}s after the command exited; terminating it")
    terminate(pgid)


def terminate(pgid):
    for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        if wait_gone(pgid, grace):
            return
    log(f"process group {pgid} survived SIGKILL")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    slots = env_int("HWORKS_HEAVY_SLOTS", 1)
    drain_s = env_int("HWORKS_HEAVY_DRAIN_S", 30)
    if slots == 0 or os.environ.get(HELD):
        try:
            os.execvp(argv[0], argv)
        except OSError as e:
            log(f"cannot run {argv[0]}: {e}")
            return 127
    lock = acquire(slots)
    try:
        record(lock, argv)
        return run(argv, drain_s)
    finally:
        lock.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
