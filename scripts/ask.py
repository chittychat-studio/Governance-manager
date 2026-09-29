"""Ask only for fields detect could not fill, then emit a validated intake (SPEC I2–I5, I5a).

Questions come from a fixed bank (I5a). Each maps to exactly one intake field and asks
about a fact or convention, never about which controls the user wants (I5).
Required unknown fields are asked first; optional ones only with the remaining
budget; never more than 7 questions (I4). Any required field still empty → refuse,
naming it, with no output (I2).

Usage:
  python scripts/ask.py <detected.json> --out intake.json            (interactive)
  python scripts/ask.py <detected.json> --answers a.json --out intake.json  (non-interactive)
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from intake import CONVENTION_KEYS, OPTIONAL, REQUIRED, IntakeError, enum_for, validate  # noqa: E402

MAX_QUESTIONS = 7

# I5a: fixed bank. kind: one = single choice, many = comma list, text = free text.
QUESTION_BANK = {
    "app_type": ("one", "What kind of application is this?"),
    "stack": ("text", "What is the stack, as framework-database (for example fastapi-postgres)?"),
    "data_classes": ("many", "Which kinds of data does the app store or process?"),
    "exposure": ("one", "Is the app reachable from the public internet, or internal only?"),
    "tenancy": ("one", "Does one deployment serve one customer (single) or many customers (multi)?"),
    "agent": ("many", "Which coding agents are used on this repo?"),
    "test_cmd": ("text", "What command runs the test suite?"),
    "integrations": ("many-free", "Which third-party services does the app call (comma separated, blank for none)?"),
    "regulation": ("many-free", "Which regulations apply to this app, if any (comma separated, blank for none)?"),
    "pkg_mgr": ("one", "Which package manager does the repo use?"),
    "branch_rule": ("text", "What is the branch rule (for example: no direct pushes to main)?"),
    "banned_libs": ("many-free", "Which libraries are banned in this repo (comma separated, blank for none)?"),
}


def plan_questions(unknown):
    """Return the fields to ask, required first, capped at 7 (I3, I4)."""
    req = [f for f in REQUIRED if f in unknown]
    opt = [f for f in OPTIONAL if f in unknown]
    return (req + opt)[:MAX_QUESTIONS]


def parse_answer(field, raw):
    """Parse and check a raw answer against the field's enum (I1a). Returns value or raises."""
    kind, _ = QUESTION_BANK[field]
    allowed = enum_for(field)
    if isinstance(raw, list):
        items = [str(x).strip() for x in raw]
    else:
        items = [x.strip() for x in str(raw).split(",")] if kind.startswith("many") else [str(raw).strip()]
    items = [x for x in items if x]
    if allowed is not None:
        bad = [x for x in items if x not in allowed]
        if bad:
            raise IntakeError(f"{field}: {bad} not in {allowed} (I1a)")
    if kind.startswith("many"):
        return items
    return items[0] if items else ""


def build_intake(detected, answers):
    """Merge detected values and answers into the intake shape (I1)."""
    merged = {**detected, **{k: v for k, v in answers.items() if v not in (None, "", [])}}
    intake = {k: merged[k] for k in REQUIRED if k in merged}
    for k in ("integrations", "regulation"):
        if k in merged:
            intake[k] = merged[k]
    conv = {k: merged[k] for k in CONVENTION_KEYS if k in merged}
    if conv:
        intake["conventions"] = conv
    for k in REQUIRED:
        if k not in intake:
            raise IntakeError(f"refused: required field '{k}' is empty (I2)")
    return validate(intake)


# Corrections to detected facts may only keep or raise risk. Lowering it goes through an exception (T6, X4).
RISK_ORDER = {"exposure": ["internal", "public"], "tenancy": ["single", "multi"]}


def apply_corrections(detected, corrections):
    """Return detected facts with the user's corrections applied (I3a). Refuses risk-lowering changes."""
    out = dict(detected)
    applied = []
    for field, raw in corrections.items():
        if field not in QUESTION_BANK:
            raise IntakeError(f"refused: unknown field '{field}'")
        value = parse_answer(field, raw)
        old = detected[field]
        if field == "data_classes":
            dropped = sorted(set(old) - set(value) - {"none"})
            if dropped:
                raise IntakeError(f"refused: removing detected data class(es) {dropped} would lower the tier. "
                                  "If detection is wrong, keep them and record a tier exception with "
                                  "scripts/exceptions.py --tier N --reason ... (T6, X4)")
        if field in RISK_ORDER and RISK_ORDER[field].index(value) < RISK_ORDER[field].index(old):
            raise IntakeError(f"refused: changing detected {field} {old!r} to {value!r} would lower the tier. "
                              "Record a tier exception instead (T6, X4)")
        if value != old:
            applied.append({"field": field, "detected": old, "answer": value})
        out[field] = value
    return out, applied


def run(detect_result, answer_source):
    """Ask planned questions via answer_source(field, question) and return intake (I2–I5)."""
    asked = {}
    for field in plan_questions(detect_result["unknown"]):
        kind, text = QUESTION_BANK[field]
        allowed = enum_for(field)
        raw = answer_source(field, text + (f" Options: {', '.join(allowed)}." if allowed else ""))
        if raw is None:
            continue
        asked[field] = parse_answer(field, raw)
    return build_intake(detect_result["detected"], asked), list(asked)


def main(argv=None):
    """CLI entry point (I2–I5)."""
    ap = argparse.ArgumentParser(description="Governor intake questions")
    ap.add_argument("detected")
    ap.add_argument("--answers", help="JSON file of field -> answer (non-interactive)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    result = json.loads(Path(args.detected).read_text(encoding="utf-8"))
    if args.answers:
        given = json.loads(Path(args.answers).read_text(encoding="utf-8"))
        source = lambda field, q: given.get(field)  # noqa: E731
    else:
        def source(field, q):
            return input(q + " ") or None
    try:
        intake, asked = run(result, source)
    except IntakeError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    Path(args.out).write_text(json.dumps(intake, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"intake written to {args.out}; asked {len(asked)} question(s): {asked}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
