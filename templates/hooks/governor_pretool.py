"""PreToolUse guard (SPEC P6, P7, P8, P9, P10, P12, L5). Stdlib only (P5).

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
CD_IN = re.compile(r"(^|[;&|(]\s*|\s)(cd|pushd|set-location|sl|chdir)\s", re.I)
NO_WORKAROUND = ("Do not look for another way to do this; tell the user what was blocked and why "
                 "(Governor rule, SPEC L5).")


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
    for globs in (cfg.get("allow_if_clean") or {}).values():
        gc.record_manifest_baseline(event, root, globs)   # P10a: first tool call of the session sets the baseline
    if tool.startswith("mcp__") and cfg.get("mcp_allowlist_rule"):
        server = tool.split("__")[1] if tool.count("__") >= 2 else tool
        if server not in cfg.get("mcp_allow", []):
            return "deny", cfg["mcp_allowlist_rule"], f"MCP server '{server}' is not in mcp_allow"
    if tool == "Monitor" and ti.get("ws") and cfg.get("monitor_ws_rule"):
        return "ask", cfg["monitor_ws_rule"], "Monitor opens a WebSocket connection (outbound network)"
    if tool in gc.SHELL_TOOLS and (tool != "Monitor" or "command" in ti):
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
                hits = [s for s in segs if pat.search(s)]
                if not hits:
                    continue
                globs = (cfg.get("allow_if_clean") or {}).get(rule["rule"])
                if exempt and globs and any(a.search(s) for s in hits for a in exempt) and \
                        (not gc.manifests_unchanged(event, root, globs) or CD_IN.search(cmd)):
                    exempt = []   # P10a: manifests changed this session, or a cd moved the restore elsewhere: ask
                if any(not any(a.search(s) for a in exempt) for s in hits):
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
        cfg = gc.load_config()
        decision, rule, text = decide(event, cfg)
    except Exception as exc:  # noqa: BLE001 - fail closed
        print(f"Governor pretool hook error, blocking (fail closed): {exc}", file=sys.stderr)
        return 2
    if decision is None:
        return 0
    if decision == "deny":
        print(f"Blocked by Governor rule {rule}: {text}{gc.explain(cfg, rule)}\n{NO_WORKAROUND}", file=sys.stderr)
        gc.log(event, f"deny {rule} tool={event.get('tool_name')}")
        return 2
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                             "permissionDecisionReason": f"Governor rule {rule}: {text}{gc.explain(cfg, rule)}"}}))
    gc.log(event, f"ask {rule} tool={event.get('tool_name')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
