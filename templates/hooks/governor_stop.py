"""Stop hook: block "done" while test_cmd fails (SPEC P6). Stdlib only (P5).

Loop guard: after `stop_max_blocks` consecutive blocks in one session the stop is
allowed and the release is logged, so the hook cannot trap a session forever.
Skips the test run when the working tree is unchanged since the last green run.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import governor_common as gc  # noqa: E402


def tree_fingerprint(root):
    """Hash of git status + diff; None outside git."""
    try:
        st = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, timeout=30)
        df = subprocess.run(["git", "diff"], cwd=root, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if st.returncode != 0:
        return None
    return hashlib.sha256(st.stdout + df.stdout).hexdigest()


def main():
    event = {}
    try:
        event = json.loads(sys.stdin.read() or "{}")
        cfg = gc.load_config()
        rule = cfg.get("stop_tests_rule")
        if not rule or not cfg.get("test_cmd"):
            return 0
        root = gc.project_dir(event)
        st = gc.read_state(event, "stop", {"blocks": 0, "green": None})
        fp = tree_fingerprint(root)
        if fp is not None and fp == st.get("green"):
            return 0
        limit = cfg.get("stop_max_blocks", 3)
        if st["blocks"] >= limit:
            gc.log(event, f"stop_tests loop-guard released rule={rule} after {limit} blocks")
            st["blocks"] = 0
            gc.write_state(event, "stop", st)
            print(f"Governor: tests still failing after {limit} attempts; stop allowed by loop guard.",
                  file=sys.stderr)
            return 0
        try:
            r = subprocess.run(cfg["test_cmd"], shell=True, cwd=root, capture_output=True,
                               timeout=cfg.get("test_timeout", 600))
            ok, out = r.returncode == 0, (r.stdout + r.stderr).decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            ok, out = False, "test_cmd timed out"
        if ok:
            gc.log(event, f"stop_tests pass rule={rule}")
            gc.write_state(event, "stop", {"blocks": 0, "green": fp})
            return 0
        st["blocks"] += 1
        gc.write_state(event, "stop", st)
        gc.log(event, f"stop_tests block rule={rule}")
        tail = "\n".join(out.strip().splitlines()[-20:])
        print(json.dumps({"decision": "block", "reason":
                          f"Governor rule {rule}: `{cfg['test_cmd']}` is failing. Fix the tests before "
                          f"finishing.\n{tail}"}))
        return 0
    except Exception as exc:
        # Fail closed, but an error that repeats must not trap the session: same loop guard.
        marker = Path(tempfile.gettempdir()) / f"governor-stop-errors-{event.get('session_id', 'x')}"
        n = int(marker.read_text()) + 1 if marker.exists() else 1
        marker.write_text(str(n))
        print(f"Governor stop hook error ({n}): {exc}", file=sys.stderr)
        return 2 if n <= 3 else 0


if __name__ == "__main__":
    sys.exit(main())
