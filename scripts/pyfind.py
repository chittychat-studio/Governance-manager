"""Find a Python command that really starts Python 3.8+ for exec-form hooks (SPEC V6, P5)."""
import json
import os
import shutil
import subprocess

CHECK = "import sys, json; print(json.dumps(['governor-ok', sys.version_info[0], sys.version_info[1]]))"


def works(cmd):
    """True if `cmd -c CHECK` runs and exits 0 (a Windows Store alias stub fails this)."""
    if not cmd or shutil.which(cmd) is None:
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
