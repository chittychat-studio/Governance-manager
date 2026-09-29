"""Per-run cap and monthly ledger for the C1 job from docs/c1-budget.yaml (SPEC E4, C1, C1a).

Prints the per-run cap in USD (monthly cap / 31) or exits 3 when no cap is approved, or when
--runs-this-month (counted from the GitHub Actions run history, including this run) would take
spending past the approved monthly cap. No network, no model calls.
"""
import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MAX_RUNS_PER_MONTH = 31


def per_run_cap(path=ROOT / "docs" / "c1-budget.yaml"):
    """Return the per-run cap, or None when the budget is not approved (E4)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cap = data.get("monthly_cap_usd")
    if not cap or not data.get("approved_by") or not data.get("approved_on"):
        return None
    return round(float(cap) / MAX_RUNS_PER_MONTH, 2)


def main(argv=None, path=ROOT / "docs" / "c1-budget.yaml"):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-this-month", type=int, default=None,
                    help="runs of the compat workflow this calendar month, including the current one")
    args = ap.parse_args(argv)
    cap = per_run_cap(path)
    if cap is None:
        print("refused: docs/c1-budget.yaml has no approved monthly cap (E4)", file=sys.stderr)
        return 3
    if args.runs_this_month is None:
        print("refused: --runs-this-month is required so monthly spend is bounded (E4, C1a)", file=sys.stderr)
        return 3
    if args.runs_this_month > MAX_RUNS_PER_MONTH:
        print(f"refused: {args.runs_this_month} runs this month; the approved cap covers "
              f"{MAX_RUNS_PER_MONTH} runs of ${cap:.2f} (E4, C1a)", file=sys.stderr)
        return 3
    print(f"{cap:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
