"""Find a Python command that really starts Python 3.8+ for exec-form hooks (SPEC V6, P5)."""
import os
import shutil
import subprocess

CHECK = "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)"


def works(cmd):
    """True if `cmd -c CHECK` runs and exits 0 (a Windows Store alias stub fails this)."""
    if not cmd or shutil.which(cmd) is None:
        return False
    try:
        return subprocess.run([cmd, "-c", CHECK], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def default_python():
    """First working interpreter name; falls back to the platform default (lint will then fail)."""
    candidates = ["python", "python3"] if os.name == "nt" else ["python3", "python"]
    for c in candidates:
        if works(c):
            return c
    return candidates[0]
