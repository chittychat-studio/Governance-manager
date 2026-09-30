"""One-page evidence report for a repo (SPEC EV1, EV1a, EV2, EV3, X3, Q5).

Reads governance.yaml + lint + drift + Governor's last Q-series result on the reference fixture.
Framework mappings appear only when a pack rule declares them (EV2).

Usage: python scripts/report.py <repo> [--out report.md]
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drift  # noqa: E402
import friction  # noqa: E402
import governance  # noqa: E402
import lint  # noqa: E402
import packs  # noqa: E402
import render  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VERIFY_RESULT = ROOT / "verify-results" / "last.json"
MAX_LINES = 60


def last_verify(path=VERIFY_RESULT):
    """Governor's last Q-series result on the reference fixture, or None (EV1)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build(repo, today=None, verify_path=VERIFY_RESULT):
    """Return the report markdown (EV1-EV3)."""
    repo = Path(repo).resolve()
    gov = governance.read(repo)
    if gov is None:
        raise ValueError("no governance.yaml: Governor is not installed")
    today = (today or datetime.date.today()).isoformat()
    lint_fails, _ = lint.lint(repo)
    dr = drift.check(repo)
    status = "linted" if not lint_fails else "generated (lint failing)"
    t, i = gov["tier"], gov["intake"]
    lines = [f"# Governor evidence report: {repo.name}", "",
             f"{today} · Governor {gov['governor_version']} · status: **{status}**", "",
             "> This report is not a compliance certificate. It describes agent configuration only.", "",
             "## Tier", "",
             f"Tier {t['effective']}" + (f" (lowered from {t['computed']} by exception)" if t["effective"] < t["computed"]
                                       else "") + f", decided by {', '.join(t['matched'])}. "
             f"Data classes: {', '.join(i['data_classes'])}; exposure: {i['exposure']}; tenancy: {i['tenancy']}.",
             "", f"Test command run by the Stop hook: `{i['test_cmd']}`"
             + (" · corrected by the user: " + ", ".join(c["field"] for c in gov.get("corrections", []))
                if gov.get("corrections") else "")
             + (" · assumed because the answer was 'not sure': " + ", ".join(gov["assumed"]) if gov.get("assumed") else ""),
             *([f"Integrations: {', '.join(i['integrations'])}"] if i.get("integrations") else []),
             *([f"Regulations named by the user: {', '.join(i['regulation'])}. Governor maps no rules to them (EV2)."]
               if i.get("regulation") else []),
             "", "## Rules", "", "| Agent | Enforced | Advisory | Disabled |", "|---|---|---|---|"]
    mappings = []
    for agent in gov["packs"]:
        rules, disabled = render.split_rules(gov, agent)
        enf = sum(r["enforcement"] == "enforced" and r["id"] not in disabled for r in rules)
        adv = sum(r["enforcement"] == "advisory" and r["id"] not in disabled for r in rules)
        dis = sum(r["id"] in disabled for r in rules)
        lines.append(f"| {agent} | {enf} | {adv} | {dis} |")
        mappings += [(r["id"], m) for r in rules for m in r.get("mappings", [])]
    lines += ["", "## Exceptions", ""]
    exc = gov.get("exceptions", [])
    for e in exc:
        what = f"{e['rule']} disabled" if e["kind"] == "rule" else f"tier lowered to {e['tier']}"
        lines.append(f"- {what} on {e['date']} by {e['by']}: {e['reason']}")
    if not exc:
        lines.append("- None.")
    n_drift = len(dr["failures"])
    lines += ["", "## Checks", "",
              f"- Lint (V1-V7): {'pass' if not lint_fails else f'{len(lint_fails)} failure(s)'}",
              f"- Drift (D1-D2a): {'none' if not n_drift else f'{n_drift} problem(s)'}"]
    v = last_verify(verify_path)
    if v:
        lines.append(f"- Q-series on Governor's reference fixture (not this repo): {v['status']} on "
                     f"{v['date'][:10]}, Governor {v['governor_version']}, {v.get('claude_version') or 'CLI unknown'}.")
    else:
        lines.append("- Q-series on Governor's reference fixture: not run. Nothing here has been verified "
                     "against a live agent session.")
    lines += ["", "## Friction (EV4)", ""] + friction.summary_lines(repo)[:6]
    lines += ["", "## Framework mappings", ""]
    lines += [f"- {rid}: {m}" for rid, m in mappings] or ["- None declared by the selected packs."]
    lines += ["", "## Limits", "",
              "- \"Enforced\" means a Claude Code hook or permission rule acts on the agent's tool calls. "
              "It is not an operating-system sandbox and does not cover code a human runs.",
              f"- Packs are {packs.signature_status()}.",
              "- Advisory rules are instructions the agent may not follow."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    """CLI (EV1)."""
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("repo")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    try:
        text = build(args.repo)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    if len(text.splitlines()) > MAX_LINES:
        print(f"report exceeds {MAX_LINES} lines (EV1a)", file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(governance.cli(main)())
