"""Select packs by pure lookup on (tier, family, agent) (SPEC P1, P1a, P4).

Named select_pack.py, not select.py: a scripts/select.py would shadow the stdlib
`select` module (used by subprocess) for anything run from scripts/.

Usage: python scripts/select_pack.py <intake.json> [--tier N]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from packs import PACKS_DIR, PackError, resolve  # noqa: E402
from tier import compute_tier  # noqa: E402


# P1a: JavaScript/TypeScript stacks share the node family; anything else without its own pack gets generic.
NODE_STACKS = {"next", "nextjs", "react", "vite", "react-vite", "node", "nodejs", "express", "node-express", "nuxt",
               "vue", "svelte", "sveltekit", "remix", "astro", "nest", "nestjs", "javascript", "typescript", "js", "ts"}


def family(stack):
    """The pack family for a stack, by lookup (P1a): exact pack, else node, else generic."""
    stack = str(stack or "").strip().lower()
    if stack and (PACKS_DIR / "tier1" / stack).is_dir():
        return stack
    first = stack.split("-", 1)[0]
    if stack in NODE_STACKS or first in NODE_STACKS or (stack.startswith("react-") or stack.startswith("node-")):
        return "node"
    return "generic"


def family_rule_ids(fam, tier=3, agent="claude-code"):
    """Rule ids a family's pack resolves to (I3a: a stack correction may not move to a family with fewer rules)."""
    try:
        return {r["id"] for r in resolve(f"tier{tier}/{fam}/{agent}")[0]}
    except PackError:
        return set()


def pack_id(tier, stack, agent):
    """Lookup key (P1, P1a): the stack's family, never a refusal for an unknown stack."""
    return f"tier{tier}/{family(stack)}/{agent}"


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
    ap = argparse.ArgumentParser(allow_abbrev=False)
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
