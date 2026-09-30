"""Ask only for fields detect could not fill, then emit a validated intake (SPEC I1e, I2–I5, I5a, I5b).

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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from intake import CONVENTION_KEYS, OPTIONAL, REQUIRED, IntakeError, enum_for, validate  # noqa: E402

MAX_QUESTIONS = 7

# I5a, I5b: fixed bank in plain words. kind: one = single choice, many = comma list, text = free text.
QUESTION_BANK = {
    "app_type": ("one", "What are you building?"),
    "stack": ("one-free", "What is it built with? Pick one, or type the framework-database name if you know it "
                          "(for example fastapi-postgres)."),
    "data_classes": ("many", "What information does it keep or handle? Pick all that apply."),
    "exposure": ("one", "Can anyone on the internet open it, or only you or your team?"),
    "tenancy": ("one", "Will different customers or organisations share this one app, each seeing only their own data?"),
    "agent": ("many", "Which AI coding assistants do you use in this project?"),
    "test_cmd": ("text", "How do you run your automated tests? Type the command, or 'none' if there are no tests yet."),
    "integrations": ("many-free", "Which outside services does the app talk to (for example Stripe, Supabase, OpenAI)? "
                                  "Leave blank if none."),
    "regulation": ("many-free", "Does any law or standard apply that you know of (for example GDPR, HIPAA)? "
                                "Leave blank if none or not sure."),
    "pkg_mgr": ("one", "Which tool installs your packages?"),
    "branch_rule": ("text", "Do you have a rule for your main branch (for example: no direct pushes to main)? "
                            "Leave blank if none."),
    "banned_libs": ("many-free", "Are there any libraries the project must not use? Leave blank if none."),
}
# I5b: one plain line per option. NOT_SURE is offered where a safe default exists (I1e).
NOT_SURE = "not sure"
OPTION_HELP = {
    "app_type": {"api": "a backend that other programs call, with no screens of its own",
                 "web-spa": "a website or web app that runs in the browser",
                 "fullstack": "a web app with screens and its own server or database",
                 "worker": "a background job or script that runs on its own",
                 "cli": "a command-line tool",
                 NOT_SURE: "Governor assumes a full web app with a server"},
    "stack": {"javascript": "JavaScript or TypeScript: Next.js, React, Vite, Node, Supabase, Firebase",
              "python": "Python: FastAPI, Django, Flask",
              NOT_SURE: "Governor uses its general rules, which work for any project"},
    "data_classes": {"none": "nothing about people (for example a calculator or a game)",
                     "pii": "anything about a person: names, emails, phone numbers, addresses",
                     "auth": "user accounts, passwords or logins",
                     "payments": "card or bank details, or it takes payments",
                     "health": "medical or health information",
                     NOT_SURE: "Governor assumes it holds personal information"},
    "exposure": {"public": "anyone on the internet can reach it",
                 "internal": "only you or your team, on your own computer or a private network",
                 NOT_SURE: "Governor assumes anyone on the internet can reach it"},
    "tenancy": {"single": "one person, one team or one customer",
                "multi": "many customers or organisations, each with their own data",
                NOT_SURE: "Governor assumes many customers share it"},
    "agent": {"claude-code": "Claude Code", "codex": "OpenAI Codex"},
    "pkg_mgr": {"pip": "Python's pip", "poetry": "Poetry (Python)", "uv": "uv (Python)", "npm": "npm (JavaScript)",
                "pnpm": "pnpm (JavaScript)", "yarn": "Yarn (JavaScript)"},
}
# I1e: what "not sure" records. Always the higher-risk value; never lowers a tier.
NOT_SURE_VALUE = {"app_type": "fullstack", "exposure": "public", "tenancy": "multi", "stack": "unknown"}
NOT_SURE_WORDS = {"not sure", "not-sure", "unsure", "don't know", "dont know", "do not know", "idk", "?", "unknown"}
STACK_WORDS = {"javascript": "node", "typescript": "node", "js": "node", "ts": "node", "python": "python"}


NOT_SURE_PHRASES = ("not sure", "unsure", "don't know", "dont know", "do not know", "idk", "no idea", "not certain")
NO_TESTS = {"none", "no", "no tests", "no test", "n/a", "na", "nothing", "none yet", "no tests yet", "not yet"}
STACK_WORDS.update({w: "node" for w in ("react", "next", "nextjs", "next.js", "vue", "nuxt", "svelte", "sveltekit",
                                         "node", "nodejs", "node.js", "express", "vite", "remix", "astro")})
STACK_WORDS.update({w: "python" for w in ("flask", "django")})


def _clean(raw):
    """Lower-case, trim, and drop trailing punctuation: 'Public.' -> 'public' (I5b)."""
    return str(raw).strip().strip(".!?,;:'\"").strip().lower()


def is_not_sure(raw):
    t = _clean(raw)
    return t in NOT_SURE_WORDS or any(p in t for p in NOT_SURE_PHRASES)


def options_for(field):
    """Options shown to the user (I5b): enum values plus not-sure, each with its plain line."""
    return OPTION_HELP.get(field)


def plan_questions(unknown):
    """Return the fields to ask, required first, capped at 7 (I3, I4)."""
    req = [f for f in REQUIRED if f in unknown]
    opt = [f for f in OPTIONAL if f in unknown]
    return (req + opt)[:MAX_QUESTIONS]


def parse_answer(field, raw, assumed=None):
    """Parse and check a raw answer against the field's enum (I1a). 'not sure' records the higher-risk value and
    notes the field in `assumed` (I1e). Returns value or raises."""
    kind, _ = QUESTION_BANK[field]
    allowed = enum_for(field)
    if field == "test_cmd" and not isinstance(raw, list) and (is_not_sure(raw) or _clean(raw) in NO_TESTS):
        return "none"   # I1c: no test suite (yet); the Stop-hook gate is then inactive rather than stuck
    if field == "data_classes":
        items = raw if isinstance(raw, list) else [x for x in str(raw).split(",")]
        if any(is_not_sure(x) for x in items):
            if assumed is not None:
                assumed.append(field)
            raw = sorted({str(x).strip() for x in items if str(x).strip() and not is_not_sure(x)} - {"none"} | {"pii"})
    elif field in NOT_SURE_VALUE and not isinstance(raw, list) and is_not_sure(raw):
        if assumed is not None:
            assumed.append(field)
        return NOT_SURE_VALUE[field]
    if field == "stack" and not isinstance(raw, list):
        word = _clean(raw)
        if word in STACK_WORDS:
            return STACK_WORDS[word]
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", word):
            raise IntakeError(f"{field}: {str(raw).strip()!r} isn't one of the choices. Answer javascript, python or "
                              "not sure (or a name like fastapi-postgres) (I5b)")
        return word
    if isinstance(raw, list):
        if not kind.startswith("many") and len(raw) != 1:
            raise IntakeError(f"{field}: expected one value, got a list of {len(raw)} (I1a)")
        items = [str(x).strip() for x in raw]
    else:
        items = [x.strip() for x in str(raw).split(",")] if kind.startswith("many") else [str(raw).strip()]
    items = [x for x in items if x]
    if allowed is not None:
        items = [_clean(x) if _clean(x) in allowed else x for x in items]
        bad = [x for x in items if x not in allowed]
        if bad:
            extra = " or not sure" if field in NOT_SURE_VALUE or field == "data_classes" else ""
            raise IntakeError(f"{field}: {', '.join(repr(b) for b in bad)} isn't one of the choices: "
                              f"{', '.join(allowed)}{extra} (I1a)")
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


def apply_corrections(detected, corrections, assumed=None, previous=()):
    """Return detected facts with the user's corrections applied (I3a). Refuses risk-lowering changes.
    `previous`: fields filled from the user's earlier answers, not detected. Changing those skips the per-field risk
    refusal; the tier-drop check in init (T6) still needs an exception."""
    out = dict(detected)
    applied = []
    for field, raw in corrections.items():
        if field not in QUESTION_BANK:
            raise IntakeError(f"refused: unknown field '{field}'")
        mark = []
        value = parse_answer(field, raw, mark)
        old = detected[field]
        if mark:  # I1e: "not sure" never lowers a detected fact
            if field == "data_classes":
                value = sorted((set(old) | set(value)) - {"none"})
                if assumed is not None:
                    assumed.extend(mark)
            elif field not in RISK_ORDER:
                value = old   # "not sure" about a detected stack or app type: keep what was detected
            elif assumed is not None:
                assumed.extend(mark)
        if field == "stack" and value != old:
            from select_pack import family, family_rule_ids
            lost = family_rule_ids(family(old)) - family_rule_ids(family(value))
            if lost:
                raise IntakeError(f"refused: changing the detected stack {old!r} to {value!r} would drop rules "
                                  f"{sorted(lost)} (I3a). If detection is wrong, record an exception with "
                                  "/governor:except instead")
        if field in previous:
            if value != old:
                applied.append({"field": field, "detected": old, "answer": value})
            out[field] = value
            continue
        if field == "data_classes":
            dropped = sorted(set(old) - set(value) - {"none"})
            if dropped:
                raise IntakeError(f"refused: removing detected data class(es) {dropped} would lower the tier. "
                                  "If detection is wrong, keep them and ask for a tier exception with "
                                  "/governor:except --tier N --reason \"why\" (T6, X4)")
        if field == "agent":
            dropped = sorted(set(old) - set(value))
            if dropped:
                raise IntakeError(f"refused: removing detected agent(s) {dropped} would switch enforcement off "
                                  "for them (I3a)")
        if field == "test_cmd" and str(value).strip().lower() == "none" and str(old).strip().lower() != "none":
            raise IntakeError(f"refused: changing the detected test command {old!r} to 'none' would switch the "
                              "Stop-hook test gate off (I1c). Record a rule exception for it instead (X1)")
        if field in RISK_ORDER and RISK_ORDER[field].index(value) < RISK_ORDER[field].index(old):
            raise IntakeError(f"refused: changing detected {field} {old!r} to {value!r} would lower the tier. "
                              "If that is right, use /governor:except --tier N --reason \"why\" (T6, X4)")
        if value != old:
            applied.append({"field": field, "detected": old, "answer": value})
        out[field] = value
    return out, applied


def run(detect_result, answer_source, assumed=None):
    """Ask planned questions via answer_source(field, question) and return intake (I2–I5)."""
    asked = {}
    assumed = assumed if assumed is not None else []
    for field in plan_questions(detect_result["unknown"]):
        kind, text = QUESTION_BANK[field]
        help_ = options_for(field)
        raw = answer_source(field, text + (" Options: " + "; ".join(f"{k} ({v})" for k, v in help_.items()) + "."
                                           if help_ else ""))
        if raw is None:
            continue
        asked[field] = parse_answer(field, raw, assumed)
    return build_intake(detect_result["detected"], asked), list(asked)


def main(argv=None):
    """CLI entry point (I2–I5)."""
    ap = argparse.ArgumentParser(allow_abbrev=False, description="Governor intake questions")
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
