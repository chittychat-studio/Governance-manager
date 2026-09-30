"""Plain-language status: is Governor on, what tier and why, what you are protected from (SPEC S1, EV4, P12).

Read-only. Usage: python scripts/status.py <repo>
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import friction  # noqa: E402
import governance  # noqa: E402
import packs  # noqa: E402
import render  # noqa: E402

TIER_WORDS = {1: "basic protection", 2: "extra care", 3: "strictest"}
REASONS = {"T2": "it handles payments or health data",
           "T3": "it holds personal data and is public or shared by many customers",
           "T4": "it holds personal data or user logins",
           "T5": "no personal data, logins or payments were found or reported"}


BLOCKING_HOOKS = ("bash_deny", "path_deny", "path_deny_write", "guard", "mcp_allowlist", "secret_scan", "stop_tests",
                  "repeat_fail")


def _blocks(rule):
    """A rule is listed as 'blocked' if anything in it blocks outright; 'ask first' only if all it does is ask."""
    h = rule.get("hook") or {}
    return bool(rule.get("deny")) or any(h.get(k) for k in BLOCKING_HOOKS)


def build(repo):
    repo = Path(repo).resolve()
    gov = governance.read(repo)
    if gov is None:
        return ["Governor is not installed in this repo. Run /governor:init to set it up."], 1
    t, i = gov["tier"], gov["intake"]
    why = "; ".join(dict.fromkeys(REASONS.get(m, m) for m in t.get("matched", [])))
    lines = [f"Governor is on. Tier {t['effective']} ({TIER_WORDS.get(t['effective'], '')}), because {why}."]
    if t["effective"] < t["computed"]:
        lines.append(f"Lowered from tier {t['computed']} by an exception you recorded.")
    lines.append(f"Why: data {', '.join(i['data_classes'])}; {i['exposure']}; {i['tenancy']} customer"
                 f"{'s' if i['tenancy'] == 'multi' else ''}.")
    if gov.get("assumed"):
        lines.append(f"Assumed because you answered 'not sure': {', '.join(gov['assumed'])}.")
    lines.append(f"Signature: {packs.signature_status()}.")
    if "claude-code" not in gov["packs"]:
        lines.append("No Claude Code rules are installed; Codex rules are advice only.")
        return lines, 0
    rules, disabled = render.split_rules(gov, "claude-code")
    on = [r for r in rules if r["id"] not in disabled]
    blocks = [r for r in on if r["enforcement"] == "enforced" and _blocks(r)]
    asks = [r for r in on if r["enforcement"] == "enforced" and r not in blocks]
    lines += ["", "The agent is blocked from:"] + [f"- {r['text']}" for r in blocks]
    lines += ["", "The agent must ask you first before:"] + [f"- {r['text']}" for r in asks]
    adv = [r for r in on if r["enforcement"] == "advisory"]
    if adv:
        lines += ["", "Told to the agent, but not enforced:"] + [f"- {r['text']}" for r in adv]
    if disabled:
        lines += ["", "Switched off by your exceptions:"] + [f"- {rid}: {why}" for rid, why in disabled.items()]
    lines += ["", *friction.summary_lines(repo)]
    lines += ["", "To allow an MCP server you trust (run it yourself, in a terminal outside Claude Code):",
              f"  python3 {Path(__file__).resolve().parent / 'init.py'} . --answers .claude/governor/answers.json "
              "--host claude-code --mcp-allow NAME --human"]
    return lines, 0


def main(argv=None):
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("repo")
    args = ap.parse_args(argv)
    lines, code = build(args.repo)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(governance.cli(main)())
