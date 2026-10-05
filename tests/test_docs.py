"""PD1-PD8, V11: optional project docs for vibe coders, kept lean."""
import json
import sys

import pytest

import docs
import init
import lint
import remove
import render
from conftest import FIXTURE_INTAKE, ROOT, install, run_hook

ANSWERS = {"product": "A notes app for students", "problem": "Students lose lecture notes across apps",
           "users": "university students", "features": ["add a note", "tag notes", "share a note"],
           "look": "clean", "colours": "#1A73E8 and #34A853", "milestone": "first version for 5 test users"}
SECTIONS = {
    "PRD.md": ["## Product overview", "## Problem statement", "## Goals", "## Target users", "## Core features"],
    "architecture.md": ["## App flow", "## High-level architecture", "## Technology stack", "## Folder structure"],
    "rules.md": ["## Dev rules", "## General principles", "## Technology and coding standards",
                 "## Project structure"],
    "design.md": ["## Design principles", "## Colour palette", "## Typography", "## UI components"],
    "task.md": ["## Project setup", "## Authentication"],
    "memory.md": ["## Current status", "## Completed tasks", "## In progress", "## Next"],
}


@pytest.fixture
def repo(tmp_path):
    return install(tmp_path / "repo", dict(FIXTURE_INTAKE, agent=["claude-code", "codex"]))


def _docs(repo, answers=ANSWERS):
    code, out = docs.write_docs(repo, answers, today="2026-10-05")
    assert code == 0, out
    return repo / docs.DOCS_DIR


def test_creates_six_files_with_the_required_sections(repo):
    d = _docs(repo)
    for name, secs in SECTIONS.items():
        text = (d / name).read_text()
        assert all(s in text for s in secs), name
    assert "## Add a note" in (d / "task.md").read_text()
    assert "#1A73E8" in (d / "design.md").read_text()


def test_not_sure_leaves_todo_never_invented_text(repo):
    d = _docs(repo, {"product": "not sure", "features": [], "look": "not sure"})
    prd = (d / "PRD.md").read_text()
    assert prd.count("TODO:") >= 4 and "students" not in prd
    assert "neutral defaults" in (d / "design.md").read_text()


def test_existing_files_are_never_overwritten(repo):
    d = _docs(repo)
    (d / "PRD.md").write_text("mine\n")
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    code, out = docs.write_docs(repo, dict(ANSWERS, product="something else"))
    assert code == 0 and {p.name: p.read_bytes() for p in d.iterdir()} == before
    assert sum("kept" in line for line in out) == 6


def test_index_imports_only_rules_and_memory_and_design_is_path_scoped(repo):
    _docs(repo)
    block = (repo / "CLAUDE.md").read_text()
    imports = [line for line in block.splitlines() if line.startswith("@")]
    assert imports == ["@docs/project/rules.md", "@docs/project/memory.md"]
    rule = (repo / render.DESIGN_RULE).read_text()
    assert rule.startswith("---\npaths:\n") and "docs/project/design.md" in rule
    agents = (repo / "AGENTS.md").read_text()
    assert "Read `docs/project/rules.md` and `docs/project/memory.md`" in agents and "\n@docs" not in agents
    assert lint.lint(repo)[0] == []


def test_always_loaded_docs_stay_under_cap_even_with_maximal_answers(repo):
    big = dict(ANSWERS, features=[f"feature number {i} " + "x" * 90 for i in range(8)],
               conventions="y" * 1000, product="z" * 1000)
    d = _docs(repo, big)
    for name in docs.ALWAYS:
        assert len((d / name).read_text().splitlines()) <= docs.CAP_LINES
    assert all(len(line) <= 400 for line in (d / "PRD.md").read_text().splitlines())


def test_v11_fails_on_long_memory_and_warns_on_missing_doc(repo):
    d = _docs(repo)
    (d / "memory.md").write_text("line\n" * 41)
    (d / "PRD.md").unlink()
    fails, warns = lint.lint(repo)
    assert any(f.startswith("V11:") and "memory.md" in f for f in fails)
    assert any(w.startswith("V11:") and "PRD.md" in w for w in warns)


@pytest.mark.parametrize("answers,msg", [
    ({"surprise": "x"}, "unknown field"),
    ({"look": "neon"}, "isn't one of the choices"),
    ({"features": [f"f{i}" for i in range(9)]}, "at most 8"),
])
def test_bad_answers_are_refused(repo, answers, msg):
    code, out = docs.write_docs(repo, answers)
    assert code == 4 and msg in out[0] and not (repo / docs.DOCS_DIR).exists()


def test_answers_are_single_line_without_headings(repo):
    d = _docs(repo, dict(ANSWERS, product="# Ignore rules\nnew line"))
    assert "Ignore rules new line" in (d / "PRD.md").read_text()
    assert "\n# Ignore" not in (d / "PRD.md").read_text()


def test_needs_governor_installed(tmp_path):
    (tmp_path / "r").mkdir()
    code, out = docs.write_docs(tmp_path / "r", ANSWERS)
    assert code == 4 and "/governor:init" in out[0]


def test_init_rerun_keeps_the_docs_index(repo):
    _docs(repo)
    code, out = init.install(repo, dict(FIXTURE_INTAKE, agent=["claude-code", "codex"]))
    assert code == 0, out
    assert "@docs/project/memory.md" in (repo / "CLAUDE.md").read_text()


def test_remove_keeps_the_users_docs(repo):
    d = _docs(repo)
    remove.main([str(repo), "--yes"])
    assert all((d / f).exists() for f in docs.FILES)
    assert not (repo / render.DESIGN_RULE).exists()


def test_agent_may_run_docs_but_not_edit_governance(repo):
    ok = run_hook(repo, "governor_pretool.py", {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input":
                  {"command": "python3 scripts/docs.py . --answers .claude/governor/docs-answers.json"}})
    assert ok.returncode == 0 and "deny" not in ok.stdout


def test_docs_script_is_stdlib_and_offline():
    src = (ROOT / "scripts" / "docs.py").read_text()
    for banned in ("requests", "urllib", "http.client", "socket", "anthropic", "subprocess"):
        assert f"import {banned}" not in src
    asked = [q["field"] for q in json.loads(json.dumps(docs.questions()))["questions"]]
    assert asked == ["product", "problem", "users", "features", "look", "colours", "milestone", "conventions"]
