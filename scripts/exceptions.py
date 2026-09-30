"""Record an opt-down exception in governance.yaml (SPEC X1-X4, T6).

Usage:
  python scripts/exceptions.py <repo> --rule P9-db-dump --reason "why, at least 20 characters"
  python scripts/exceptions.py <repo> --tier 2 --reason "why, at least 20 characters"
Re-run scripts/render.py afterwards. Disabled rules render as "disabled: <reason>" (X2).
"""
import argparse
import datetime
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import governance  # noqa: E402
from packs import resolve  # noqa: E402

MIN_REASON = 20


class ExceptionRefused(ValueError):
    """Exception request does not meet X1/X4."""


def git_user(repo):
    """git config user.email, recorded with the exception (X1)."""
    try:
        r = subprocess.run(["git", "config", "user.email"], cwd=repo, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        r = None
    email = r.stdout.strip() if r and r.returncode == 0 else ""
    if not email:
        raise ExceptionRefused("refused: git config user.email is not set (X1)")
    return email


def add(repo, rule=None, tier=None, reason="", today=None, user=None):
    """Add a rule or tier exception and rebuild governance.yaml (X1, X4)."""
    gov = governance.read(repo)
    if gov is None:
        raise ExceptionRefused("refused: no governance.yaml; run governance.py first")
    reason = (reason or "").strip()
    if len(reason) < MIN_REASON:
        raise ExceptionRefused(f"refused: --reason must be at least {MIN_REASON} characters (X1)")
    if (rule is None) == (tier is None):
        raise ExceptionRefused("refused: give exactly one of --rule or --tier")
    entry = {"reason": reason, "date": (today or datetime.date.today()).isoformat(),
             "by": user or git_user(repo)}
    if rule:
        known = {r["id"] for a in gov["packs"].values() for r in resolve(a["pack_id"])[0]}
        if rule not in known:
            raise ExceptionRefused(f"refused: {rule} is not in the selected packs")
        entry = {"kind": "rule", "rule": rule, **entry}
    else:
        if not 1 <= tier < gov["tier"]["computed"]:
            raise ExceptionRefused(f"refused: tier exception must lower the computed tier "
                                   f"{gov['tier']['computed']} (T6, X4)")
        entry = {"kind": "tier", "tier": tier, **entry}
    exceptions = gov.get("exceptions", []) + [entry]
    new = governance.build(gov["intake"], exceptions, gov.get("mcp_allow", []), gov.get("hook_python"),
                           gov.get("corrections", []), gov.get("assumed", []))
    governance.write(repo, new)
    return entry


def main(argv=None):
    """CLI (X1-X4)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--rule")
    ap.add_argument("--tier", type=int)
    ap.add_argument("--reason", required=True)
    args = ap.parse_args(argv)
    try:
        entry = add(args.repo, args.rule, args.tier, args.reason)
    except ExceptionRefused as exc:
        print(str(exc), file=sys.stderr)
        return 5
    print(f"exception recorded: {entry}. Re-run scripts/render.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
