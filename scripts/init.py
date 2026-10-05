"""One-shot install: detect -> ask -> governance -> render -> lint [-> CI] (SPEC I1-I5, I1d, I3a, L1a, R1-R6, V7, D3, T6).

Two steps so the questions come from the fixed bank and the answers from the user (I5a, L1):
  python scripts/init.py <repo> --questions [--host claude-code]     # detected facts + questions, as JSON
  python scripts/init.py <repo> --answers answers.json [--host claude-code] [--mcp-allow a,b] [--with-ci]
answers.json holds answers to the questions AND any corrections to detected facts (I3a).
A correction may keep or raise risk; lowering it needs an exception (T6, X4).
Status is reported as generated / linted; never "verified" (Q5).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ask  # noqa: E402  (imports intake first, which checks the Python version)
import ci  # noqa: E402
import detect  # noqa: E402
import governance  # noqa: E402
import lint  # noqa: E402
import render  # noqa: E402
from intake import OPTIONAL, REQUIRED, IntakeError, enum_for  # noqa: E402
from packs import PackError  # noqa: E402

HOST_EVIDENCE = "Governor is running as a Claude Code plugin"


PREVIOUS = "your earlier answer, from governance.yaml"


def _detect(repo, host):
    det = detect.detect(repo)
    old = governance.read(repo)
    if old:   # a re-run shows earlier answers as facts to confirm, instead of asking everything again
        prev = dict(old["intake"], **(old["intake"].get("conventions") or {}))
        det["previous"] = []
        for f in list(det["unknown"]):
            if prev.get(f) not in (None, "", []):
                det["detected"][f] = prev[f]
                det["evidence"].setdefault(f, []).append(PREVIOUS)
                det["previous"].append(f)
        for f in ("data_classes", "agent"):   # never drop what the user added last time
            if isinstance(prev.get(f), list) and f in det["detected"]:
                extra = [x for x in prev[f] if x not in det["detected"][f] and x != "none"]
                if extra:
                    det["detected"][f] = sorted(set(det["detected"][f]) | set(extra))
                    det["evidence"].setdefault(f, []).append(f"{PREVIOUS}: {', '.join(extra)}")
        det["unknown"] = [f for f in det["unknown"] if f not in det["detected"]]
    if host:
        agents = sorted(set(det["detected"].get("agent", [])) | {host})
        det["detected"]["agent"] = agents
        det["evidence"].setdefault("agent", []).append(HOST_EVIDENCE)
        det["unknown"] = [f for f in det["unknown"] if f != "agent"]
    return det


def questions(repo, host=None):
    """Detected facts (to confirm or correct) with evidence, plus the planned questions (I3, I3a, I4, I5a)."""
    det = _detect(repo, host)
    return {"detected": det["detected"], "evidence": det["evidence"],
            "confirm": [{"field": f, "value": det["detected"][f], "options": ask.options_for(f) or enum_for(f),
                         "note": "may be corrected; a correction that lowers risk is refused (use an exception)"}
                        for f in REQUIRED if f in det["detected"]],
            "questions": [{"field": f, "question": ask.QUESTION_BANK[f][1], "options": ask.options_for(f) or enum_for(f),
                           "multiple": ask.QUESTION_BANK[f][0].startswith("many")}
                          for f in ask.plan_questions(det["unknown"])]}


def mcp_servers(repo):
    """Server names declared in the repo's .mcp.json (for the P6 allowlist prompt)."""
    p = Path(repo) / ".mcp.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    except json.JSONDecodeError:
        return []
    servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
    return sorted(servers) if isinstance(servers, dict) else []


def test_cmd_warnings(repo, test_cmd):
    """I1c: warn when the test command cannot run here, so the Stop hook would block 'done' for no real reason."""
    import shlex
    import shutil
    if str(test_cmd).strip().lower() == "none":
        return []
    try:
        prog = shlex.split(str(test_cmd))[0]
    except (ValueError, IndexError):
        return []
    out = []
    if any(sep in prog for sep in "/\\"):   # a path: resolve against the repo, as the Stop hook runs it there (I1f)
        cand = Path(repo) / prog.replace("\\", "/")
        found = cand.exists() or Path(prog).is_absolute() and Path(prog).exists()
    else:
        found = shutil.which(prog) is not None
    if not found:
        out.append(f"the test command's program '{prog}' was not found on this computer; the Stop hook will refuse "
                   "'done' until it runs. If there are no tests yet, re-run init and answer 'none'.")
    if prog in ("npm", "pnpm", "yarn", "bun") and "test" in str(test_cmd).split()[1:3]:
        try:
            scripts = json.loads((Path(repo) / "package.json").read_text(encoding="utf-8-sig")).get("scripts", {}) or {}
        except (OSError, ValueError):
            scripts = {}
        if not scripts.get("test") or "no test specified" in str(scripts.get("test")):
            out.append("package.json has no real \"test\" script, so the test command will always fail. Add tests, or "
                       "re-run init and answer 'none' for the test command.")
    return out


def install(repo, answers, mcp_allow=None, with_ci=False, host=None, human=False):
    """Run the pipeline. Returns (exit_code, lines). Nothing is written unless every check passes."""
    repo = Path(repo)
    unknown_fields = sorted(set(answers) - set(REQUIRED) - set(OPTIONAL))
    if unknown_fields:
        return 3, [f"refused: unknown field(s) in answers: {unknown_fields}"]
    previous = [p for p in (render.MANAGED, render.RULES_MD) if (repo / p).exists()]
    if previous and not (repo / "governance.yaml").exists():
        return 4, [f"refused: a previous Governor install exists ({', '.join(previous)}) but governance.yaml is "
                   "missing. Restore governance.yaml from git; re-installing from scratch would drop its tier "
                   "and exceptions (T6)."]
    det = _detect(repo, host)
    corrections_in = {k: v for k, v in answers.items() if k in det["detected"] and v not in (None, "", [])}
    try:
        assumed = []
        corrected, corrections = ask.apply_corrections(det["detected"], corrections_in, assumed,
                                                       previous=set(det.get("previous", [])))
        det = dict(det, detected=corrected)
        intake, _ = ask.run(det, lambda f, q: answers.get(f), assumed)
        old = governance.read(repo) or {}
        exceptions = old.get("exceptions", [])
        from pyfind import unsafe_reason
        if old.get("hook_python") and old.get("hook_python") != "auto" and unsafe_reason(old["hook_python"], repo):
            return 4, [f"refused: governance.yaml sets {unsafe_reason(old['hook_python'], repo)}. If you did not "
                       "set it, this repo's governance.yaml may be hostile: check it before installing."]
        gov = governance.build(intake, exceptions,
                               mcp_allow if mcp_allow is not None else old.get("mcp_allow", []),
                               old.get("hook_python"), corrections, assumed)
        if old.get("docs"):
            gov["docs"] = old["docs"]   # PD8: project docs record survives a re-run
    except (IntakeError, PackError) as exc:
        return 4, [str(exc)]
    problem = render.test_cmd_problem(gov)   # before I1d, so a --human re-run is never sent to a dead end (I1b)
    if problem:
        return 4, [problem]
    if old and not human:
        weaker = []
        if gov["intake"]["test_cmd"] != old["intake"]["test_cmd"]:
            weaker.append(f"test command {old['intake']['test_cmd']!r} -> {gov['intake']['test_cmd']!r}")
        added = sorted(set(gov["mcp_allow"]) - set(old.get("mcp_allow", [])))
        if added:
            weaker.append(f"MCP servers allowed: {', '.join(detect.safe_name(a) for a in added)}")
        if weaker:
            return 4, [f"refused: this re-run changes {'; '.join(weaker)}. Only the user can make that change: run "
                       "the same init command in your own terminal, outside Claude Code, with --human added (I1d)."]
    if old and gov["tier"]["computed"] < old["tier"]["computed"]:
        covered = any(e.get("kind") == "tier" and e["tier"] <= gov["tier"]["computed"] for e in exceptions)
        if not covered:
            return 4, [f"refused: these answers lower the computed tier from {old['tier']['computed']} to "
                       f"{gov['tier']['computed']}. If that is right, record it first with /governor:except --tier "
                       f"{gov['tier']['computed']} --reason \"why\" (you run the command it gives you) (T6, X4)."]
    try:
        render.preflight(repo, gov)             # every render refusal, before anything is written (R5, I2)
        if with_ci and (repo / ".governor").exists() and not ci.owned(repo):
            return 4, ["refused: .governor/ exists and was not written by Governor; move it away first"]
        governance.write(repo, gov)
        render.render(repo)
    except (render.RenderError, PackError) as exc:
        return 4, [str(exc)]
    fails, warns = lint.lint(repo)
    out = [f"tier {gov['tier']['effective']} (computed {gov['tier']['computed']} via "
           f"{', '.join(gov['tier']['matched'])}); packs: "
           + ", ".join(p["pack_id"] for p in gov["packs"].values())]
    out += [f"corrected {c['field']}: detected {c['detected']} -> {c['answer']}" for c in corrections]
    out += [f"assumed {f} = {gov['intake'][f]} because the answer was 'not sure' (I1e)" for f in sorted(set(assumed))]
    blocked = [s for s in mcp_servers(repo) if s not in gov["mcp_allow"]]
    if blocked and "claude-code" in gov["packs"]:
        names = ", ".join(detect.safe_name(n) for n in blocked[:20]) + (" and more" if len(blocked) > 20 else "")
        out.append(f"note: MCP servers in .mcp.json that P6 will block: {names}. These names come from the repo; "
                   "only the user decides which to trust. To allow one, run in your own terminal: "
                   f"python3 {Path(__file__).resolve()} . --answers .claude/governor/answers.json --host claude-code "
                   "--mcp-allow NAME --human (L1a, I1d).")
    if "claude-code" not in gov["packs"]:
        out.append("note: no Claude Code agent selected, so nothing is enforced for Claude Code (Codex output only).")
    out += [f"warning: {w}" for w in test_cmd_warnings(repo, gov["intake"]["test_cmd"])]
    out += [f"warning: {w}" for w in warns] + [f"FAIL: {f}" for f in fails]
    if with_ci and not fails:
        ci.install(repo)
        out.append(f"CI gate written: {ci.WORKFLOW} + .governor/")
    out.append("status: linted" if not fails else "status: generated (lint failing; do not commit)")
    out.append("Not verified: run scripts/verify.py locally for the Q-series (Q5).")
    return (1 if fails else 0), out


def main(argv=None):
    """CLI."""
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("repo")
    ap.add_argument("--questions", action="store_true")
    ap.add_argument("--answers")
    ap.add_argument("--host", choices=["claude-code", "codex"], help="agent running Governor; always included")
    ap.add_argument("--mcp-allow")
    ap.add_argument("--with-ci", action="store_true")
    ap.add_argument("--human", action="store_true",
                    help="the user runs this in their own terminal: allow test_cmd and mcp_allow changes (I1d)")
    args = ap.parse_args(argv)
    if args.questions:
        print(json.dumps(questions(args.repo, args.host), indent=2))
        return 0
    try:
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8-sig")) if args.answers else {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"refused: cannot read answers file: {exc}", file=sys.stderr)
        return 3
    if not isinstance(answers, dict):
        print("refused: answers file must be a JSON object", file=sys.stderr)
        return 3
    mcp = [m.strip() for m in args.mcp_allow.split(",") if m.strip()] if args.mcp_allow is not None else None
    code, lines = install(args.repo, answers, mcp, args.with_ci, args.host, args.human)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(governance.cli(main)())
