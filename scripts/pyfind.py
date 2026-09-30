"""Find a Python command that really starts Python 3.8+ for exec-form hooks (SPEC V6, P5)."""
import json
import os
import shutil
import subprocess

CHECK = "import sys, json; print(json.dumps(['governor-ok', sys.version_info[0], sys.version_info[1]]))"


SAFE_NAMES = ("python3", "python", "py")


def unsafe_reason(cmd, repo=None):
    """V6a: why cmd must not be used as the hook interpreter, or None. Checked before anything executes it."""
    cmd = str(cmd or "")
    if cmd in SAFE_NAMES:
        return None
    if not os.path.isabs(cmd) or any(c.isspace() for c in cmd):
        return (f"hook_python {cmd!r} must be python3, python, py or an absolute path to an interpreter outside the "
                "repository (V6a)")
    if repo is not None:
        root = os.path.realpath(str(repo))
        real = os.path.realpath(cmd)
        if real == root or real.startswith(root.rstrip(os.sep) + os.sep):
            return f"hook_python {cmd!r} is inside the repository, so the repo could replace it (V6a)"
    return None


def works(cmd, repo=None):
    """True if `cmd -c CHECK` runs and exits 0 (a Windows Store alias stub fails this). Unsafe values (V6a) are
    never executed."""
    if not cmd or unsafe_reason(cmd, repo) or shutil.which(cmd) is None:
        return False
    try:
        r = subprocess.run([cmd, "-c", CHECK], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    try:
        tag, major, minor = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError, TypeError):
        return False   # e.g. /bin/true, or a Store alias that prints nothing
    return r.returncode == 0 and tag == "governor-ok" and (major, minor) >= (3, 8)


def default_python():
    """First working interpreter name; falls back to the platform default (lint will then fail)."""
    candidates = ["python", "python3"] if os.name == "nt" else ["python3", "python"]
    for c in candidates:
        if works(c):
            return c
    return candidates[0]
