"""Project docs for vibe coders (SPEC PD1-PD8). Stdlib only (E8); no network, no model calls (E2, NX4).

Usage: python scripts/docs.py <repo> --questions          # JSON: the fixed question bank (PD2)
       python scripts/docs.py <repo> --answers a.json     # write missing docs/project/*.md, record them, re-render

Files are filled from the answers and governance.yaml only. An existing file is never overwritten (PD4).
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import detect  # noqa: E402
import governance  # noqa: E402

DOCS_DIR = "docs/project"
FILES = ["PRD.md", "architecture.md", "rules.md", "design.md", "task.md", "memory.md"]
ALWAYS = ["rules.md", "memory.md"]      # imported every session (PD5)
CAP_LINES = 40                          # PD5/PD6
TEXT_CAP, FEATURE_CAP, MAX_FEATURES = 300, 80, 8
NOT_SURE = {"", "not sure", "not sure yet", "don't know", "dont know", "idk", "skip", "none yet"}
TODO = "TODO: not decided yet; fill this in when you know."

LOOKS = {
    "clean": "clean and minimal: plenty of white space, few colours, nothing decorative",
    "playful": "playful and friendly: rounded shapes, brighter colours, light-hearted words",
    "professional": "professional: calm colours, dense but tidy layouts, formal words",
    "not sure": "not decided yet: Governor writes neutral defaults you can change",
}

# Fixed bank (PD2, I5a): field, question, kind, options/help. Plain words (I5b).
QUESTIONS = [
    ("product", "In one sentence, what are you building?", "text", None),
    ("problem", "What problem does it solve, and for whom?", "text", None),
    ("users", "Who will use it? (for example: small shop owners, students, your own team)", "text", None),
    ("features", "List the main things it must do, 1 to 8 short items separated by commas "
                 "(for example: sign up, add a note, share a note).", "list", None),
    ("look", "How should it look and feel?", "one", LOOKS),
    ("colours", "Any brand colours? Give hex codes like #1A73E8, or say not sure.", "text", None),
    ("milestone", "What are you working towards right now? (for example: first version for 5 test users)",
     "text", None),
    ("conventions", "Any coding rules you already follow? (optional; for example: TypeScript only, no default "
                    "exports)", "text", None),
]
FIELDS = {q[0] for q in QUESTIONS}

FLOWS = {
    "api": "Clients (apps or other services) -> API endpoints -> business logic -> data store; responses go back as data.",
    "web-spa": "Browser UI -> calls to a backend or hosted service -> data store; the screens run in the browser.",
    "fullstack": "Browser UI -> the app's own server (pages and API) -> business logic -> database.",
    "worker": "Trigger (schedule, queue or event) -> job logic -> data store or other services; no screens.",
    "cli": "Terminal command -> argument parsing -> core logic -> files or services -> printed result.",
}
STACK_NAMES = {"node": "JavaScript/TypeScript (Node)", "fastapi-postgres": "Python (FastAPI) with Postgres",
               "generic": "not detected", "other": "not detected"}


class DocsError(ValueError):
    pass


def _clean(v, cap=TEXT_CAP):
    """Single line, no heading markers, capped (PD2). Returns '' for not sure."""
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    s = re.sub(r"^#+\s*", "", s)
    if s.lower().strip(" .!") in NOT_SURE:
        return ""
    return s if len(s) <= cap else s[:cap - 3] + "..."


def parse(answers):
    """Validate and normalise answers (PD2). Raises DocsError naming the field."""
    unknown = sorted(set(answers) - FIELDS)
    if unknown:
        raise DocsError(f"refused: unknown field(s) in answers: {unknown} (PD2)")
    out = {f: _clean(answers.get(f)) for f in FIELDS - {"features", "look", "colours"}}
    feats = answers.get("features") or []
    if isinstance(feats, str):
        feats = feats.split(",")
    feats = [x for x in (_clean(f, FEATURE_CAP) for f in feats) if x]
    if len(feats) > MAX_FEATURES:
        raise DocsError(f"refused: {len(feats)} features; list at most {MAX_FEATURES} main ones (PD2)")
    out["features"] = feats
    look = _clean(answers.get("look")).lower() or "not sure"
    if look not in LOOKS:
        raise DocsError(f"refused: look {look!r} isn't one of the choices: {', '.join(LOOKS)} (PD2)")
    out["look"] = look
    cols = re.findall(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b", str(answers.get("colours") or ""))
    out["colours"] = [c.upper() for c in cols[:6]]
    return out


def _or_todo(s):
    return s or TODO


def folder_tree(repo, limit=30):
    """Top two directory levels, dependency/build folders skipped, names quoted (PD3, L1a)."""
    out = []
    for d in sorted(p for p in Path(repo).iterdir() if p.is_dir()):
        if d.name in detect.SKIP_DIRS or d.name.startswith("."):
            continue
        out.append(f"- {detect.safe_name(d.name + '/')}")
        for c in sorted(p for p in d.iterdir() if p.is_dir()):
            if c.name in detect.SKIP_DIRS or c.name.startswith("."):
                continue
            out.append(f"  - {detect.safe_name(c.name + '/')}")
        if len(out) >= limit:
            break
    return out[:limit] or ["- (no folders yet)"]


def _header(today):
    return (f"<!-- Created by Governor /governor:docs on {today} from your answers. This file is yours: edit it "
            "freely; Governor never overwrites it (PD4). -->")


def build(repo, gov, a, today):
    """Return {filename: text} for all six files (PD1, PD3)."""
    intake = gov["intake"]
    stack = STACK_NAMES.get(intake.get("stack"), str(intake.get("stack")))
    test = intake.get("test_cmd")
    test_line = "No tests yet (test_cmd: none)." if str(test).lower() == "none" else f"Run tests with `{test}`."
    auth = "auth" in (intake.get("data_classes") or [])
    feats = a["features"]
    h = _header(today)
    prd = [h, "# Product requirements", "", "## Product overview", _or_todo(a["product"]), "",
           "## Problem statement", _or_todo(a["problem"]), "", "## Goals", f"- Current milestone: {_or_todo(a['milestone'])}"]
    prd += [f"- Users can {f[0].lower() + f[1:]}." for f in feats] or [f"- {TODO}"]
    prd += ["", "## Target users", _or_todo(a["users"]), "", "## Core features"]
    prd += [f"{i}. {f}" for i, f in enumerate(feats, 1)] or [TODO]
    arch = [h, "# Architecture", "", "## App flow", FLOWS.get(intake.get("app_type"), TODO), "",
            "## High-level architecture",
            f"- App type: {intake.get('app_type')}. Exposure: {intake.get('exposure')}. "
            f"Data handled: {', '.join(intake.get('data_classes') or ['none'])}.",
            "- Add the main parts (UI, API, database, outside services) and how they talk to each other here.", "",
            "## Technology stack", f"- Language and framework: {stack}.", f"- {test_line}",
            "- Add the database, hosting and key libraries here as you choose them.", "",
            "## Folder structure (top two levels when this file was created)"] + folder_tree(repo)
    conv = a["conventions"]
    rules = [h, "# Project rules (loaded every session; keep under 40 lines)", "",
             "## Dev rules", f"- {test_line} Keep them passing.",
             "- Small, focused changes. One task at a time from docs/project/task.md.",
             "- Governor's safety rules are in .claude/rules/governor.md and come first.", "",
             "## General principles", "- Simple over clever. Delete code you do not need.",
             "- Never put secrets or real personal data in code, tests or logs.",
             "- Ask the user when a requirement is unclear instead of guessing.", "",
             "## Technology and coding standards", f"- Stack: {stack}.",
             f"- {conv}" if conv else "- Follow the style already used in the code.",
             "- Name things for what they do. Handle errors where they happen.", "",
             "## Project structure", "- See docs/project/architecture.md. Keep new files in the matching folder."]
    look = LOOKS[a["look"]]
    pal = a["colours"] or ["#111827 (text)", "#FFFFFF (background)", "#2563EB (primary)", "#6B7280 (muted)"]
    design = [h, "# Design", "", "## Design principles", f"- Look and feel: {look}.",
              "- Readable first: body text 16px or larger, strong contrast.", "- Same component, same behaviour, everywhere.", "",
              "## Colour palette" + ("" if a["colours"] else " (neutral defaults; replace with your brand)")]
    design += [f"- {c}" for c in pal]
    design += ["", "## Typography", "- Font: the system font stack until a brand font is chosen.",
               "- Sizes: 32 / 24 / 20 / 16 / 14 px for title, heading, subheading, body, small.", "",
               "## UI components", "- Buttons, form fields, cards, navigation, and loading / empty / error states.",
               "- List each new shared component here with one line on when to use it."]
    task = [h, "# Tasks", "", "## Project setup", "- [ ] App runs locally from a fresh clone (steps in README).",
            f"- [ ] {test_line}", "- [ ] Governor installed and committed."]
    if auth:
        task += ["", "## Authentication", "- [ ] Sign up, sign in and sign out.",
                 "- [ ] Passwords and tokens never logged or committed."]
    for f in feats:
        task += ["", f"## {f[0].upper() + f[1:]}", f"- [ ] Define what done means for: {f}.", "- [ ] Build it.",
                 "- [ ] Test it."]
    if not feats:
        task += ["", "## Features", f"- [ ] {TODO}"]
    first = "Authentication" if auth else (feats[0] if feats else "Project setup")
    memory = [h, "# Memory (loaded every session; replace, do not append; keep under 40 lines)", "",
              "## Current status", f"- Milestone: {_or_todo(a['milestone'])}", "- Docs created; no feature work recorded yet.", "",
              "## Completed tasks", "- none yet", "", "## In progress", "- none", "",
              "## Next", f"- {first} (see docs/project/task.md)", "", "## Notes", "- none"]
    return {name: "\n".join(lines) + "\n" for name, lines in
            zip(FILES, [prd, arch, rules, design, task, memory])}


def questions():
    return {"questions": [{"field": f, "question": q, "kind": k, "options": o} for f, q, k, o in QUESTIONS],
            "note": "Ask each question word for word; 'not sure' is always allowed and leaves a TODO (PD2)."}


def write_docs(repo, answers, today=None):
    """Write missing files, record them in governance.yaml, re-render (PD4, PD8). Returns (code, lines)."""
    import lint
    import render
    repo = Path(repo).resolve()
    gov = governance.read(repo)
    if gov is None:
        return 4, ["refused: Governor is not installed here; run /governor:init first (PD1)"]
    try:
        a = parse(answers)
    except DocsError as exc:
        return 4, [str(exc)]
    today = today or datetime.date.today().isoformat()
    texts = build(repo, gov, a, today)
    d = repo / DOCS_DIR
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for name, text in texts.items():
        p = d / name
        if p.exists():
            out.append(f"kept {DOCS_DIR}/{name} (already exists; yours, never overwritten)")
            continue
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        out.append(f"created {DOCS_DIR}/{name}")
    old = gov.get("docs") or {}
    gov["docs"] = {"dir": DOCS_DIR, "files": FILES, "created": old.get("created", today)}
    governance.write(repo, gov)
    render.render(repo)
    fails, warns = lint.lint(repo)
    out += [f"warning: {w}" for w in warns] + [f"FAIL: {f}" for f in fails]
    out.append("Loaded every session: rules.md and memory.md (max 40 lines each). design.md loads only for UI "
               "files; PRD.md, architecture.md and task.md are read only when a task needs them (PD5).")
    out.append("status: linted" if not fails else "status: generated (lint failing; do not commit)")
    return (1 if fails else 0), out


def main(argv=None):
    ap = argparse.ArgumentParser(allow_abbrev=False, description="Create project docs (SPEC PD1-PD8)")
    ap.add_argument("repo")
    ap.add_argument("--questions", action="store_true")
    ap.add_argument("--answers")
    args = ap.parse_args(argv)
    if args.questions:
        print(json.dumps(questions(), indent=2))
        return 0
    if not args.answers:
        ap.error("give --questions or --answers FILE")
    code, lines = write_docs(args.repo, json.loads(Path(args.answers).read_text(encoding="utf-8-sig")))
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(governance.cli(main)())
