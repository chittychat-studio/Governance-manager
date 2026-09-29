"""PreToolUse guard (SPEC P6, P7, P8, P9, P10). Stdlib only (P5).

deny -> exit 2 with the rule id on stderr; ask -> permissionDecision "ask".
Any internal error blocks (fail closed).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import governor_common as gc  # noqa: E402


def decide(event, cfg):
    """Return (decision, rule_id, message) or (None, None, None)."""
    tool = event.get("tool_name", "")
    ti = event.get("tool_input") or {}
    root = gc.project_dir(event)
    if tool.startswith("mcp__") and cfg.get("mcp_allowlist_rule"):
        server = tool.split("__")[1] if tool.count("__") >= 2 else tool
        if server not in cfg.get("mcp_allow", []):
            return "deny", cfg["mcp_allowlist_rule"], f"MCP server '{server}' is not in mcp_allow"
    if tool == "Bash":
        cmd = ti.get("command", "")
        segs = gc.normalise(cmd)
        fails = gc.read_state(event, "fails", {})
        limit = cfg.get("repeat_fail")
        if limit and fails.get(" && ".join(segs), 0) >= limit["n"]:
            return "deny", limit["rule"], f"this command already failed {limit['n']} times this session"
        for kind in ("deny", "ask"):
            for rule in cfg.get(f"bash_{kind}", []):
                pat = re.compile(rule["pattern"], re.I)
                if any(pat.search(s) for s in segs):
                    return kind, rule["rule"], rule["text"]
    for p in gc.tool_paths(ti):
        for rule in cfg.get("path_deny", []):
            if gc.path_matches(p, rule["globs"], root) and not gc.path_matches(p, rule.get("allow", []), root):
                return "deny", rule["rule"], rule["text"]
        if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            for rule in cfg.get("path_deny_write", []):
                if gc.path_matches(p, rule["globs"], root):
                    return "deny", rule["rule"], rule["text"]
    return None, None, None


def main():
    event = {}
    try:
        event = json.loads(sys.stdin.read() or "{}")
        decision, rule, text = decide(event, gc.load_config())
    except Exception as exc:  # fail closed
        print(f"Governor pretool hook error, blocking (fail closed): {exc}", file=sys.stderr)
        return 2
    if decision is None:
        return 0
    gc.log(event, f"{decision} {rule} tool={event.get('tool_name')}")
    if decision == "deny":
        print(f"Blocked by Governor rule {rule}: {text}", file=sys.stderr)
        return 2
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                             "permissionDecisionReason": f"Governor rule {rule}: {text}"}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
