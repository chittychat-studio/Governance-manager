"""PreToolUse guard (SPEC P6, P7, P8, P9, P10). Stdlib only (P5).

deny -> exit 2 with the rule id on stderr; ask -> permissionDecision "ask".
Covers the Bash and PowerShell tools. Any internal error blocks (fail closed); logging can never
change the decision.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import governor_common as gc  # noqa: E402

WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def decide(event, cfg):
    """Return (decision, rule_id, message) or (None, None, None)."""
    if not isinstance(event, dict):
        raise ValueError("event is not an object")
    tool = str(event.get("tool_name") or "")
    if not tool:
        raise ValueError("event has no tool_name")
    ti = event.get("tool_input") or {}
    if not isinstance(ti, dict):
        raise ValueError("tool_input is not an object")
    root = gc.project_dir(event)
    if tool.startswith("mcp__") and cfg.get("mcp_allowlist_rule"):
        server = tool.split("__")[1] if tool.count("__") >= 2 else tool
        if server not in cfg.get("mcp_allow", []):
            return "deny", cfg["mcp_allowlist_rule"], f"MCP server '{server}' is not in mcp_allow"
    if tool in gc.SHELL_TOOLS:
        cmd = ti.get("command", "")
        if not isinstance(cmd, str):
            raise ValueError("command is not a string")
        segs = gc.normalise(cmd, tool=tool)
        guard = cfg.get("guard")
        if guard and gc.guard_hit(cmd, tool):
            return "deny", guard["rule"], guard["text"]
        limit = cfg.get("repeat_fail")
        if limit:
            fails = gc.read_state(event, "fails", {})
            if isinstance(fails, dict) and fails.get(gc.fail_key(cmd, tool), 0) >= limit["n"]:
                return "deny", limit["rule"], f"this command already failed {limit['n']} times this session"
        allow = {rid: [re.compile(p, re.I) for p in pats] for rid, pats in (cfg.get("bash_allow") or {}).items()}
        for kind in ("deny", "ask"):
            for rule in cfg.get(f"bash_{kind}", []):
                pat = re.compile(rule["pattern"], re.I)
                exempt = allow.get(rule["rule"], [])
                if any(pat.search(s) and not any(a.search(s) for a in exempt) for s in segs):
                    return kind, rule["rule"], rule["text"]
    for p in gc.tool_paths(ti):
        for rule in cfg.get("path_deny", []):
            if gc.path_matches(p, rule["globs"], root) and not gc.path_matches(p, rule.get("allow", []), root):
                return "deny", rule["rule"], rule["text"]
        if tool in WRITE_TOOLS:
            for rule in cfg.get("path_deny_write", []):
                if gc.path_matches(p, rule["globs"], root):
                    return "deny", rule["rule"], rule["text"]
    search = []
    if tool == "Grep" and isinstance(ti.get("glob"), str):
        search.append(ti["glob"])
    if tool == "Glob" and isinstance(ti.get("pattern"), str):
        search.append(ti["pattern"])
    for g in search:
        for rule in cfg.get("path_deny", []):
            if gc.glob_may_match(g, rule["globs"]) and not any(g.endswith(a) for a in rule.get("allow", [])):
                return "deny", rule["rule"], rule["text"] + " (search pattern could select protected files)"
    return None, None, None


def main():
    event = {}
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        decision, rule, text = decide(event, gc.load_config())
    except Exception as exc:  # noqa: BLE001 - fail closed
        print(f"Governor pretool hook error, blocking (fail closed): {exc}", file=sys.stderr)
        return 2
    if decision is None:
        return 0
    if decision == "deny":
        print(f"Blocked by Governor rule {rule}: {text}", file=sys.stderr)
        gc.log(event, f"deny {rule} tool={event.get('tool_name')}")
        return 2
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                             "permissionDecisionReason": f"Governor rule {rule}: {text}"}}))
    gc.log(event, f"ask {rule} tool={event.get('tool_name')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
