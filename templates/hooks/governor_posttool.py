"""PostToolUse: secret scan on Edit/Write (P6, P11) and failure counting for Bash/PowerShell (P8). Stdlib only (P5).

The block decision is printed before anything is logged, so a logging failure cannot hide a hit.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import governor_common as gc  # noqa: E402

SECRET_PATTERNS = {
    "aws-access-key": r"\b(AKIA|ASIA)[0-9A-Z]{16}\b",
    "aws-secret-key": r"(?i)aws.{0,20}secret.{0,20}[:=]\s*['\"]?[A-Za-z0-9/+=]{40}\b",
    "private-key": r"-----BEGIN ((RSA|EC|OPENSSH|DSA|ENCRYPTED|PGP) )?PRIVATE KEY( BLOCK)?-----",
    "stripe-live-key": r"\b[sr]k_live_[0-9a-zA-Z]{16,}\b",
    "github-token": r"\b(gh[pousr]_[0-9A-Za-z]{30,}|github_pat_[0-9A-Za-z_]{40,})\b",
    "slack-token": r"\bxox[abpr]-[0-9A-Za-z-]{10,}\b",
    "anthropic-key": r"\bsk-ant-[0-9A-Za-z_-]{20,}\b",
    "openai-key": r"\bsk-(proj-)?[0-9A-Za-z_-]{32,}\b",
    "google-api-key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "url-credentials": r"\b[a-z][a-z0-9+.-]*://[^:/\s'\"@]*:[^@\s'\"/]{3,}@(?!(localhost|127\.0\.0\.1)\b)[^\s'\"]+",
    # P11: a server secret in a variable the build ships to the browser (Next.js, Vite, Expo, Create React App).
    "public-env-secret": r"\b(NEXT_PUBLIC|VITE|EXPO_PUBLIC|REACT_APP)_[A-Z0-9_]*(SECRET|SERVICE_ROLE|PRIVATE|PASSWORD)[A-Z0-9_]*\b",
    # KEY = "value" / KEY: "value" where the name says secret.
    "assigned-secret": r"(?i)\b[A-Za-z0-9_.-]*(password|passwd|pwd|secret|api_?key|access_?key|token|private_?key)"
                       r"[A-Za-z0-9_]*['\"]?\s*[:=]\s*['\"]([^'\"\s]{12,})['\"]",
    # KEY=value (.env / YAML style, unquoted): must contain a digit and must not be a call or attribute.
    "assigned-secret-env": r"(?i)\b[A-Za-z0-9_.-]*(password|passwd|pwd|secret|api_?key|access_?key|token|private_?key)"
                           r"[A-Za-z0-9_]*\s*[:=]\s*(?=[^\s'\"#]*\d)[^\s'\"#().]{12,}(?![\w(.])",
}
# Values that are clearly placeholders or read from the environment, not secrets.
PLACEHOLDER = re.compile(r"(?i)(example|changeme|change-me|placeholder|dummy|your[_-]|xxx|<[^>]*>|\$\{|\$[A-Z_]|\{[^}]*\}|"
                         r"os\.environ|getenv|environ\[|settings\.|config\.|process\.env|test-token|fake|redacted|\*{4})")


def scan_text(text):
    """Return [(pattern_name, line_no)] for secret-looking strings; values are never returned."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        for name, pat in SECRET_PATTERNS.items():
            m = re.search(pat, line)
            if m and not PLACEHOLDER.search(m.group(0)):
                hits.append((name, n))
                break
    return hits


def main():
    event = {}
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
        if not isinstance(event, dict):
            raise ValueError("event is not an object")
        cfg = gc.load_config()
        tool = str(event.get("tool_name") or "")
        ti = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
        if tool in gc.SHELL_TOOLS and cfg.get("repeat_fail"):
            resp = event.get("tool_response")
            failed = event.get("hook_event_name") == "PostToolUseFailure" or \
                (isinstance(resp, dict) and (resp.get("exit_code") not in (None, 0) or resp.get("is_error")))
            key = gc.fail_key(str(ti.get("command", "")), tool)
            fails = gc.read_state(event, "fails", {})
            fails = fails if isinstance(fails, dict) else {}
            fails[key] = fails.get(key, 0) + 1 if failed else 0
            gc.write_state(event, "fails", fails)
            return 0
        if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit") and cfg.get("secret_scan_rule"):
            root = gc.project_dir(event)
            total = []
            for p in gc.tool_paths(ti):
                path = Path(p) if Path(p).is_absolute() else root / p
                text = path.read_text(encoding="utf-8", errors="ignore") if path.is_file() else ""
                total += [(path.name, name, n) for name, n in scan_text(text)]
            if total:
                where = ", ".join(f"{f}:{n} ({name})" for f, name, n in total[:10])
                print(json.dumps({"decision": "block", "reason":
                                  f"Governor rule {cfg['secret_scan_rule']}: possible secret written at {where}. "
                                  "Remove it and load it from the environment instead." + gc.explain(cfg, cfg["secret_scan_rule"])}))
            gc.log(event, f"secret_scan ran rule={cfg['secret_scan_rule']} hits={len(total)}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Governor posttool hook error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
