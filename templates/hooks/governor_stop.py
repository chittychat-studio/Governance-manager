"""Stop hook: block "done" while test_cmd fails (SPEC P6). Stdlib only (P5).

Loop guard: after `stop_max_blocks` consecutive blocks in one session the stop is allowed and the
release is logged, so the hook cannot trap a session. Claude Code also caps Stop-hook blocks itself.
The test run is skipped only when HEAD, tracked changes (staged and unstaged) and the contents of
untracked files are all identical to the last green run.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import governor_common as gc  # noqa: E402

MAX_UNTRACKED_BYTES = 5_000_000


def _git(root, *args):
    # A repo's git config could run code (core.fsmonitor); switch that off for Governor's own git calls.
    r = subprocess.run(["git", "-c", "core.fsmonitor=", "-c", "core.untrackedCache=false", "--no-optional-locks",
                        *args], cwd=root, capture_output=True, timeout=60)
    if r.returncode != 0:
        raise OSError("git failed")
    return r.stdout


def tree_fingerprint(root):
    """Hash of HEAD + all tracked changes + untracked file contents; None outside git or on error."""
    try:
        h = hashlib.sha256()
        head = _has_head(root)
        h.update(_git(root, "rev-parse", "--verify", "-q", "HEAD") if head else b"no-head")
        h.update(_git(root, "diff", "--cached"))
        h.update(_git(root, "diff"))
        total = 0
        for rel in sorted(_git(root, "ls-files", "-o", "--exclude-standard", "-z").split(b"\0")):
            if not rel:
                continue
            p = Path(root) / rel.decode("utf-8", "replace")
            h.update(rel)
            if p.is_file():
                total += p.stat().st_size
                if total > MAX_UNTRACKED_BYTES:
                    return None  # too much to hash: always run the tests
                h.update(p.read_bytes())
        return h.hexdigest()
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _has_head(root):
    try:
        return subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=root,
                              capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main():
    event = {}
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
        if not isinstance(event, dict):
            raise ValueError("event is not an object")
        cfg = gc.load_config()
        rule = cfg.get("stop_tests_rule")
        if not rule or not cfg.get("test_cmd"):
            return 0
        root = gc.project_dir(event)
        st = gc.read_state(event, "stop", {})
        st = {"blocks": int(st.get("blocks", 0)), "errors": 0, "green": st.get("green")} if isinstance(st, dict) \
            else {"blocks": 0, "errors": 0, "green": None}
        fp = tree_fingerprint(root)
        if fp is not None and fp == st.get("green"):
            return 0
        limit = int(cfg.get("stop_max_blocks", 3))
        if st["blocks"] >= limit:
            gc.log(event, f"stop_tests loop-guard released rule={rule} after {limit} blocks")
            gc.write_state(event, "stop", {"blocks": 0, "green": st.get("green")})
            print(f"Governor: tests still failing after {limit} attempts; stop allowed by loop guard.",
                  file=sys.stderr)
            return 0
        try:
            r = subprocess.run(gc.platform_cmd(cfg["test_cmd"]), shell=True, cwd=root, capture_output=True,
                               timeout=int(cfg.get("test_timeout", 600)))
            ok, out, code = r.returncode == 0, (r.stdout + r.stderr).decode("utf-8", "replace"), r.returncode
        except subprocess.TimeoutExpired:
            ok, out, code = False, "test_cmd timed out", None
        gc.write_state(event, "stop_errors", 0)
        if ok:
            gc.write_state(event, "stop", {"blocks": 0, "green": fp})
            gc.log(event, f"stop_tests pass rule={rule}")
            return 0
        st["blocks"] += 1
        gc.write_state(event, "stop", {"blocks": st["blocks"], "green": st.get("green")})
        tail = "\n".join(out.strip().splitlines()[-20:])
        if not gc.program_found(root, cfg["test_cmd"]):
            reason = (f"Governor rule {rule}: the test command `{cfg['test_cmd']}` could not start here: its program "
                      "was not found, so Governor cannot check the tests. This is a setup problem, not a test "
                      "failure. The user can fix it by re-running Governor's init in their own terminal with a test "
                      f"command that works on this computer and --human (I1f, I1d).{gc.explain(cfg, rule)}")
        else:
            why = (f" (exit {code}: a program the tests call was not found or could not run)"
                   if code in (126, 127, 9009) else "")
            reason = (f"Governor rule {rule}: `{cfg['test_cmd']}` is failing{why}. Fix the tests before "
                      f"finishing.{gc.explain(cfg, rule)}")
        print(json.dumps({"decision": "block", "reason": f"{reason}\n{tail}"}))
        gc.log(event, f"stop_tests block rule={rule}")
        return 0
    except Exception as exc:  # noqa: BLE001
        # Fail closed, but a repeating error must not trap the session: same loop guard, kept in state.
        errs = gc.read_state(event, "stop_errors", 0)
        errs = errs + 1 if isinstance(errs, int) else 1
        gc.write_state(event, "stop_errors", errs)
        print(f"Governor stop hook error ({errs}): {exc}", file=sys.stderr)
        return 2 if errs <= 3 else 0


if __name__ == "__main__":
    sys.exit(main())
