"""Derive the tier from intake by lookup in tiers.yaml (SPEC T0-T6). No LLM (T1), no network (E2).

Usage: python scripts/tier.py <intake.json>
"""
import json
import sys
from pathlib import Path

import miniyaml

ROOT = Path(__file__).resolve().parent.parent
TIERS_PATH = ROOT / "tiers.yaml"


def load_tiers(path=TIERS_PATH):
    """Load the versioned tier table (T1)."""
    return miniyaml.load(Path(path).read_text(encoding="utf-8"))


def _matches(when, intake):
    classes = set(intake["data_classes"])
    for key, want in when.items():
        if key == "data_classes_any":
            if not classes & set(want):
                return False
        elif key == "exposure_or_tenancy":
            if not any(intake.get(k) == v for k, v in want.items()):
                return False
        elif intake.get(key) != want:
            return False
    return True


def compute_tier(intake, table=None):
    """Return (tier, [matched rule ids]); highest match wins, default T5 (T0, T2-T5)."""
    table = table or load_tiers()
    matched = [(r["tier"], r["id"]) for r in table["rules"] if _matches(r["when"], intake)]
    if not matched:
        return table["default"]["tier"], [table["default"]["id"]]
    top = max(t for t, _ in matched)
    return top, sorted({rid for t, rid in matched if t == top})


def main(argv=None):
    """CLI: print tier and the rules that decided it (T0)."""
    argv = sys.argv[1:] if argv is None else argv
    intake = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    tier, why = compute_tier(intake)
    print(json.dumps({"tier": tier, "matched": why, "tiers_version": load_tiers()["version"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
