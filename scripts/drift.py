"""Drift check: re-detect, re-tier, diff against installed governance.yaml (SPEC D1, D2, D2a, P4).

Exit 0 = no drift; 1 = drift that must be re-rendered (tier increase, data-class/exposure/tenancy
change, pack pin change, or Governor files missing). No network, no model calls (D4).

Usage: python scripts/drift.py <repo> [--json]
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import detect  # noqa: E402
import governance  # noqa: E402
import render  # noqa: E402
from packs import read_lock  # noqa: E402
from tier import compute_tier  # noqa: E402


def check(repo):
    """Return {'failures': [...], 'warnings': [...], 'tier': {...}} (D1, D2, D2a)."""
    repo = Path(repo).resolve()
    gov = governance.read(repo)
    if gov is None:
        return {"failures": ["D1: no governance.yaml; Governor is not installed"], "warnings": [], "tier": None}
    fails, warns = [], []
    old = gov["intake"]
    fresh = detect.detect(repo)["detected"]

    # D2a: facts that decide the tier. Only additions are detectable; removals need a human.
    added = sorted(set(fresh.get("data_classes", [])) - set(old["data_classes"]) - {"none"})
    if added:
        fails.append(f"D2a: new data class(es) detected: {added} (evidence in detect output)")
    for key in ("exposure", "tenancy"):
        if key in fresh and fresh[key] != old[key]:
            fails.append(f"D2a: {key} changed: governance.yaml says {old[key]!r}, repo shows {fresh[key]!r}")
    if "stack" in fresh and fresh["stack"] != old["stack"]:
        fails.append(f"D1: stack changed: {old['stack']!r} -> {fresh['stack']!r}")

    # D2: recompute the tier with the fresh facts merged in
    merged = dict(old)
    if added:
        merged["data_classes"] = sorted(set(old["data_classes"]) - {"none"} | set(added))
    for key in ("exposure", "tenancy"):
        merged[key] = fresh.get(key, old[key])
    new_tier, why = compute_tier(merged)
    tier = {"installed": gov["tier"]["computed"], "now": new_tier, "matched": why}
    if new_tier > gov["tier"]["computed"]:
        fails.append(f"D2: tier increased {gov['tier']['computed']} -> {new_tier} ({', '.join(why)})")

    # P4: installed pins vs the packs this Governor version ships
    lock = read_lock()
    for agent, p in gov["packs"].items():
        for pin in p["pins"]:
            if lock.get(pin["id"]) != pin["sha256"]:
                fails.append(f"D1: pack {pin['id']} differs from the installed pin; re-run governance + render")

    # D1 stale paths: Governor-owned files, hook targets, and rules whose paths: match nothing
    managed_p = repo / render.MANAGED
    if managed_p.exists():
        for rel in json.loads(managed_p.read_text(encoding="utf-8")).get("files", []):
            if not (repo / rel).exists():
                fails.append(f"D1: stale path: Governor file {rel} is missing")
    rules_dir = repo / ".claude" / "rules"
    for rp in sorted(rules_dir.rglob("*.md")) if rules_dir.exists() else []:
        m = re.match(r"^---\s*\n(.*?)\n---", rp.read_text(encoding="utf-8"), re.S)
        if not m:
            continue
        globs = re.findall(r"^\s*-\s*['\"]?([^'\"\n]+)['\"]?\s*$", m.group(1), re.M)
        for g in globs:
            if not any(repo.glob(g)):
                warns.append(f"D1: stale path: {rp.relative_to(repo).as_posix()} paths '{g}' matches no files")
    return {"failures": fails, "warnings": warns, "tier": tier}


def main(argv=None):
    """CLI (D1-D2a)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    res = check(args.repo)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        for w in res["warnings"]:
            print("warning:", w)
        for f in res["failures"]:
            print("DRIFT:", f)
        print("drift: none" if not res["failures"] else f"drift: {len(res['failures'])} problem(s); "
              "re-run detect/ask, governance.py and render.py")
    return 1 if res["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
