"""Select packs by pure lookup on (tier, stack, agent) (SPEC P1, P4).

Named select_pack.py, not select.py: a scripts/select.py would shadow the stdlib
`select` module (used by subprocess) for anything run from scripts/.

Usage: python scripts/select_pack.py <intake.json> [--tier N]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from packs import PackError, resolve  # noqa: E402
from tier import compute_tier  # noqa: E402


def pack_id(tier, stack, agent):
    """Lookup key (P1)."""
    return f"tier{tier}/{stack}/{agent}"


def select(intake, tier):
    """Return {agent: {pack_id, rules, pins}}; refuse if any agent has no pack (P1, P4)."""
    out = {}
    for agent in intake["agent"]:
        pid = pack_id(tier, intake["stack"], agent)
        rules, pins = resolve(pid)
        out[agent] = {"pack_id": pid, "rules": rules, "pins": pins}
    return out


def main(argv=None):
    """CLI (P1)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("intake")
    ap.add_argument("--tier", type=int)
    args = ap.parse_args(argv)
    intake = json.loads(Path(args.intake).read_text(encoding="utf-8"))
    tier = args.tier or compute_tier(intake)[0]
    try:
        sel = select(intake, tier)
    except PackError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    print(json.dumps({a: {"pack_id": s["pack_id"], "rule_ids": [r["id"] for r in s["rules"]],
                          "pins": s["pins"]} for a, s in sel.items()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
