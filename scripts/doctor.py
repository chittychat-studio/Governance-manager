"""Audit an existing repo's agent config against its derived tier (SPEC DR1). Read-only.

Derives the tier from detect (+ optional --answers). Unknown facts are filled with the
worst case (exposure public, tenancy multi, data_classes pii) and the report says so.
Checks each rule of the selected pack against .claude/settings.json, registered hooks and
instruction files (CLAUDE.md, AGENTS.md, .claude/rules/). Writes nothing.

Usage: python scripts/doctor.py <repo> [--answers answers.json] [--json]
Exit: 0 no gaps, 1 gaps found, 2 cannot audit (no pack for the stack).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import detect  # noqa: E402
import render  # noqa: E402
from ask import parse_answer  # noqa: E402
import governance  # noqa: E402
from intake import REQUIRED, IntakeError  # noqa: E402
from packs import PackError  # noqa: E402
from select_pack import select  # noqa: E402
from tier import compute_tier  # noqa: E402

WORST_CASE = {"exposure": "public", "tenancy": "multi", "data_classes": ["pii"], "agent": ["claude-code"]}
HOOK_EVENT_FOR = {"secret_scan": "PostToolUse", "stop_tests": "Stop", "repeat_fail": "PostToolUseFailure"}


def derive_intake(repo, answers=None):
    """Facts for the audit (DR1): an installed governance.yaml wins; else detected facts + answers, with
    unknowns filled by the stated worst case. Freshly detected data classes are always added."""
    det = detect.detect(repo)["detected"]
    gov = governance.read(repo)
    answers = {k: parse_answer(k, v) for k, v in (answers or {}).items()}
    assumed = []
    if gov:
        intake = dict(gov["intake"], **answers)
        extra = sorted(set(det.get("data_classes", [])) - set(intake["data_classes"]))
        if extra:
            intake["data_classes"] = sorted(set(intake["data_classes"]) - {"none"} | set(extra))
            assumed.append(f"data_classes also include {extra} (detected now, not in governance.yaml)")
        return intake, assumed, gov
    intake = {**det, **answers}
    for k in REQUIRED:
        if k not in intake:
            if k in WORST_CASE:
                intake[k] = WORST_CASE[k]
                assumed.append(f"{k}={WORST_CASE[k]} (unknown; worst case assumed)")
            elif k == "test_cmd":
                assumed.append("test_cmd unknown: the Stop-hook rule cannot be satisfied")
    if "data_classes" in det and "data_classes" not in answers and "pii" not in intake["data_classes"]:
        intake["data_classes"] = sorted(set(intake["data_classes"]) | {"pii"})
        assumed.append("data_classes also include pii (not ruled out; worst case assumed)")
    return intake, assumed, None


def _settings(repo):
    p = Path(repo) / ".claude" / "settings.json"
    try:
        return json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    except json.JSONDecodeError:
        return {}


def _instructions(repo):
    repo = Path(repo)
    texts = [p.read_text(encoding="utf-8", errors="ignore") for p in
             [repo / "CLAUDE.md", repo / "AGENTS.md", repo / ".claude" / "CLAUDE.md"] if p.exists()]
    rules = repo / ".claude" / "rules"
    if rules.exists():
        texts += [p.read_text(encoding="utf-8", errors="ignore") for p in rules.rglob("*.md")]
    return "\n".join(texts)


def audit(repo, answers=None):
    """Return report dict: tier, assumptions, per-rule findings, missing rule ids (DR1)."""
    repo = Path(repo).resolve()
    try:
        intake, assumed, gov = derive_intake(repo, answers)
    except IntakeError as exc:
        return {"error": str(exc), "assumed": []}
    if "stack" not in intake:
        return {"error": "stack unknown: cannot select a pack", "assumed": assumed}
    tier, why = compute_tier(intake)
    disabled = {e["rule"]: e["reason"] for e in (gov or {}).get("exceptions", []) if e.get("kind") == "rule"}
    lowered = [e["tier"] for e in (gov or {}).get("exceptions", []) if e.get("kind") == "tier"]
    if lowered and min(lowered) < tier:
        assumed.append(f"tier lowered from {tier} to {min(lowered)} by a recorded exception")
        tier = min(lowered)
    try:
        sel = select(dict(intake, agent=["claude-code"]), tier)["claude-code"]
    except PackError as exc:
        return {"error": str(exc), "tier": tier, "assumed": assumed}
    s = _settings(repo)
    s = s if isinstance(s, dict) else {}
    perms = s.get("permissions", {}) if isinstance(s.get("permissions"), dict) else {}
    hooks = s.get("hooks", {}) if isinstance(s.get("hooks"), dict) else {}
    text = _instructions(repo)
    findings = []
    for r in sel["rules"]:
        if r["id"] in disabled:
            findings.append({"rule": r["id"], "ok": True, "gaps": [], "disabled": disabled[r["id"]]})
            continue
        gaps = []
        for key in ("deny", "ask"):
            missing = [x for x in r.get(key, []) if x not in perms.get(key, []) and x not in perms.get("deny", [])]
            if missing:
                gaps.append(f"settings.json {key} missing {missing}")
        h = r.get("hook") or {}
        events = {"PreToolUse"} if any(k in h for k in ("bash_deny", "bash_ask", "path_deny", "path_deny_write",
                                                      "mcp_allowlist")) else set()
        events |= {e for k, e in HOOK_EVENT_FOR.items() if k in h}
        for ev in sorted(events):
            handlers = [x for g in hooks.get(ev, []) for x in g.get("hooks", [])]
            if not handlers:
                gaps.append(f"no {ev} hook registered")
            elif not any(render.is_governor_hook(x) for x in handlers):
                gaps.append(f"{ev} hook present but not Governor's; not audited")
        if r["enforcement"] == "advisory" and r["id"] not in text:
            gaps.append("rule not in CLAUDE.md / AGENTS.md / .claude/rules")
        findings.append({"rule": r["id"], "ok": not gaps, "gaps": gaps})
    return {"tier": tier, "matched": why, "pack": sel["pack_id"], "assumed": assumed, "findings": findings,
            "missing": [f["rule"] for f in findings if not f["ok"]]}


def main(argv=None):
    """CLI (DR1)."""
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("repo")
    ap.add_argument("--answers")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    answers = json.loads(Path(args.answers).read_text(encoding="utf-8-sig")) if args.answers else None
    rep = audit(args.repo, answers)
    if args.json:
        print(json.dumps(rep, indent=2))
    elif "error" in rep:
        print(f"doctor: cannot audit: {rep['error']}")
    else:
        print(f"doctor: tier {rep['tier']} ({', '.join(rep['matched'])}), pack {rep['pack']}")
        for a in rep["assumed"]:
            print(f"  assumed: {a}")
        for f in rep["findings"]:
            label = "disabled" if f.get("disabled") else ("ok      " if f["ok"] else "MISSING ")
            print(f"  {label} {f['rule']}" + (f": {'; '.join(f['gaps'])}" if f["gaps"] else "")
                  + (f": {f['disabled']}" if f.get("disabled") else ""))
        print(f"{len(rep['missing'])} rule(s) missing" if rep["missing"] else "no gaps")
    if "error" in rep:
        return 2
    return 1 if rep["missing"] else 0


if __name__ == "__main__":
    sys.exit(governance.cli(main)())
