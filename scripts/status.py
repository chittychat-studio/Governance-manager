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

TIER_WORDS = {1: "basic protection", 2: "extra care for personal data or logins",
              3: "strictest: public app, personal data shared by many customers, payments or health data"}


def build(repo):
    repo = Path(repo).resolve()
    gov = governance.read(repo)
    if gov is None:
        return ["Governor is not installed in this repo. Run /governor:init to set it up."], 1
    t, i = gov["tier"], gov["intake"]
    lines = [f"Governor is on. Tier {t['effective']} ({TIER_WORDS.get(t['effective'], '')})."]
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
    blocks = [r for r in on if r["enforcement"] == "enforced" and r.get("ask") is None and not
              (r.get("hook") or {}).get("bash_ask")]
    asks = [r for r in on if r["enforcement"] == "enforced" and r not in blocks]
    lines += ["", "The agent is blocked from:"] + [f"- {r['text']}" for r in blocks]
    lines += ["", "The agent must ask you first before:"] + [f"- {r['text']}" for r in asks]
    adv = [r for r in on if r["enforcement"] == "advisory"]
    if adv:
        lines += ["", "Told to the agent, but not enforced:"] + [f"- {r['text']}" for r in adv]
    if disabled:
        lines += ["", "Switched off by your exceptions:"] + [f"- {rid}: {why}" for rid, why in disabled.items()]
    lines += ["", *friction.summary_lines(repo)]
    return lines, 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    args = ap.parse_args(argv)
    lines, code = build(args.repo)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
