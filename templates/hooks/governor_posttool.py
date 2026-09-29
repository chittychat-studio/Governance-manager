"""PostToolUse: secret scan on Edit/Write (P6) and failure counting for Bash (P8). Stdlib only (P5)."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import governor_common as gc  # noqa: E402

SECRET_PATTERNS = {
    "aws-access-key": r"\b(AKIA|ASIA)[0-9A-Z]{16}\b",
    "private-key": r"-----BEGIN (RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
    "stripe-live-key": r"\b[sr]k_live_[0-9a-zA-Z]{16,}\b",
    "github-token": r"\bgh[pousr]_[0-9A-Za-z]{30,}\b",
    "slack-token": r"\bxox[abpr]-[0-9A-Za-z-]{10,}\b",
    "anthropic-key": r"\bsk-ant-[0-9A-Za-z_-]{20,}\b",
    "openai-key": r"\bsk-(proj-)?[0-9A-Za-z_-]{32,}\b",
    "google-api-key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "assigned-secret": r"(?i)\b(password|passwd|secret|api_key|apikey|token)\b\s*[:=]\s*['\"][^'\"\s]{12,}['\"]",
}
PLACEHOLDER = re.compile(r"(?i)(example|changeme|placeholder|dummy|your[_-]|xxx|<.*>|\$\{)")


def scan_text(text):
    """Return [(pattern_name, line_no)] for secret-looking strings; values are never returned."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        for name, pat in SECRET_PATTERNS.items():
            m = re.search(pat, line)
            if m and not PLACEHOLDER.search(m.group(0)):
                hits.append((name, n))
    return hits


def main():
    event = {}
    try:
        event = json.loads(sys.stdin.read() or "{}")
        cfg = gc.load_config()
        tool = event.get("tool_name", "")
        if tool == "Bash" and cfg.get("repeat_fail"):
            resp = event.get("tool_response") or {}
            failed = event.get("hook_event_name") == "PostToolUseFailure" or \
                (isinstance(resp, dict) and (resp.get("exit_code") not in (None, 0) or resp.get("is_error")))
            key = " && ".join(gc.normalise((event.get("tool_input") or {}).get("command", "")))
            fails = gc.read_state(event, "fails", {})
            fails[key] = fails.get(key, 0) + 1 if failed else 0
            gc.write_state(event, "fails", fails)
            return 0
        if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit") and cfg.get("secret_scan_rule"):
            root = gc.project_dir(event)
            total = []
            for p in gc.tool_paths(event.get("tool_input") or {}):
                path = Path(p) if Path(p).is_absolute() else root / p
                text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
                total += [(path.name, name, n) for name, n in scan_text(text)]
            gc.log(event, f"secret_scan ran rule={cfg['secret_scan_rule']} hits={len(total)}")
            if total:
                where = ", ".join(f"{f}:{n} ({name})" for f, name, n in total[:10])
                print(json.dumps({"decision": "block", "reason":
                                  f"Governor rule {cfg['secret_scan_rule']}: possible secret written at {where}. "
                                  "Remove it and load it from the environment instead."}))
        return 0
    except Exception as exc:
        print(f"Governor posttool hook error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
