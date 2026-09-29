"""Per-run cap for the C1 job from docs/c1-budget.yaml (SPEC E4, C1).

Prints the per-run cap in USD (monthly cap / 31, so at most one run per day stays within the
month) or exits 3 when no cap has been approved. No network, no model calls.
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def per_run_cap(path=ROOT / "docs" / "c1-budget.yaml"):
    """Return the per-run cap, or None when the budget is not approved (E4)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cap = data.get("monthly_cap_usd")
    if not cap or not data.get("approved_by") or not data.get("approved_on"):
        return None
    return round(float(cap) / 31, 2)


def main():
    cap = per_run_cap()
    if cap is None:
        print("refused: docs/c1-budget.yaml has no approved monthly cap (E4)", file=sys.stderr)
        return 3
    print(f"{cap:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
