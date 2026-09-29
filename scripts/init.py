"""One-shot install: detect -> ask -> governance -> render -> lint [-> CI] (SPEC I1-I5, R1-R6, V7, D3).

Two steps so the questions come from the fixed bank and the answers from the user (I5a, L1):
  python scripts/init.py <repo> --questions            # print the questions to ask, as JSON
  python scripts/init.py <repo> --answers answers.json [--mcp-allow a,b] [--with-ci]
Status is reported as generated / linted; never "verified" (Q5).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ask  # noqa: E402
import ci  # noqa: E402
import detect  # noqa: E402
import governance  # noqa: E402
import lint  # noqa: E402
import render  # noqa: E402
from intake import IntakeError, enum_for  # noqa: E402
from packs import PackError  # noqa: E402


def questions(repo):
    """Detected facts with evidence + the planned questions (I3, I4, I5a)."""
    det = detect.detect(repo)
    return {"detected": det["detected"], "evidence": det["evidence"],
            "questions": [{"field": f, "question": ask.QUESTION_BANK[f][1], "options": enum_for(f),
                           "multiple": ask.QUESTION_BANK[f][0].startswith("many")}
                          for f in ask.plan_questions(det["unknown"])]}


def install(repo, answers, mcp_allow=None, with_ci=False):
    """Run the pipeline. Returns (exit_code, lines)."""
    det = detect.detect(repo)
    planned = set(ask.plan_questions(det["unknown"]))
    extra = set(answers) - planned
    if extra:
        return 3, [f"refused: answers given for fields that were not asked: {sorted(extra)} (I3)"]
    try:
        intake, _ = ask.run(det, lambda f, q: answers.get(f))
        old = governance.read(repo) or {}
        gov = governance.build(intake, old.get("exceptions", []),
                               mcp_allow if mcp_allow is not None else old.get("mcp_allow", []),
                               old.get("hook_python", "auto"))
    except (IntakeError, PackError) as exc:
        return 4, [str(exc)]
    governance.write(repo, gov)
    render.render(repo)
    fails, warns = lint.lint(repo)
    out = [f"tier {gov['tier']['effective']} (computed {gov['tier']['computed']} via "
           f"{', '.join(gov['tier']['matched'])}); packs: "
           + ", ".join(p["pack_id"] for p in gov["packs"].values())]
    out += [f"warning: {w}" for w in warns] + [f"FAIL: {f}" for f in fails]
    if with_ci and not fails:
        ci.install(repo)
        out.append(f"CI gate written: {ci.WORKFLOW} + .governor/")
    out.append("status: linted" if not fails else "status: generated (lint failing; do not commit)")
    out.append("Not verified: run scripts/verify.py locally for the Q-series (Q5).")
    return (1 if fails else 0), out


def main(argv=None):
    """CLI."""
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--questions", action="store_true")
    ap.add_argument("--answers")
    ap.add_argument("--mcp-allow")
    ap.add_argument("--with-ci", action="store_true")
    args = ap.parse_args(argv)
    if args.questions:
        print(json.dumps(questions(args.repo), indent=2))
        return 0
    answers = json.loads(Path(args.answers).read_text(encoding="utf-8")) if args.answers else {}
    mcp = [m.strip() for m in args.mcp_allow.split(",") if m.strip()] if args.mcp_allow is not None else None
    code, lines = install(args.repo, answers, mcp, args.with_ci)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
