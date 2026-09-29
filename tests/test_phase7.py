"""Phase 7 tests: E1 (plugin packaging), E7 (Codex AGENTS.md renderer)."""
import json
import re
import shutil
import subprocess

import pytest
import yaml

import init
import lint
import packs
import render
import report
from conftest import FIXTURE_INTAKE, ROOT, install

BOTH = dict(FIXTURE_INTAKE, agent=["claude-code", "codex"])


def test_codex_block_rendered_and_linted(tmp_path):
    repo = install(tmp_path / "r", BOTH)
    text = (repo / "AGENTS.md").read_text()
    assert render.BLOCK_START in text and "- P6-rm-rf:" in text and "none of them is enforced for Codex" in text
    assert lint.lint(repo)[0] == []


def test_codex_is_advisory_only_in_coverage_and_report(tmp_path):
    """R6: per-agent coverage is honest: Codex gets instructions only."""
    repo = install(tmp_path / "r", BOTH)
    cov = (repo / render.COVERAGE_MD).read_text()
    assert "## codex" in cov and "Enforced: 0 · Advisory: 13 · Disabled: 0" in cov
    text = report.build(repo, verify_path=tmp_path / "none")
    assert "| codex | 0 | 13 | 0 |" in text and "| claude-code | 16 | 2 | 0 |" in text


def test_user_agents_md_kept_and_block_replaced(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("# My agent notes\n\nKeep this.\n")
    install(repo, BOTH)
    render.render(repo)
    text = (repo / "AGENTS.md").read_text()
    assert text.startswith("# My agent notes\n\nKeep this.\n")
    assert text.count(render.BLOCK_START) == 1


def test_lint_catches_missing_codex_rule(tmp_path):
    repo = install(tmp_path / "r", BOTH)
    p = repo / "AGENTS.md"
    p.write_text(p.read_text().replace("- P6-force-push:", "- gone:"))
    assert any("AGENTS.md missing P6-force-push" in f for f in lint.lint(repo)[0])


def test_codex_only_touches_no_claude_settings(tmp_path):
    repo = install(tmp_path / "r", dict(FIXTURE_INTAKE, agent=["codex"]))
    assert not (repo / ".claude" / "settings.json").exists()
    assert (repo / "AGENTS.md").exists() and lint.lint(repo)[0] == []


def test_codex_packs_superset():
    """P3 holds for the Codex chain too."""
    ids = [{r["id"] for r in packs.resolve(f"tier{n}/fastapi-postgres/codex")[0] if "codex" in r["agents"]}
           for n in (1, 2, 3)]
    assert ids[0] < ids[1] < ids[2]


def fixture_copy(tmp_path):
    repo = tmp_path / "app"
    shutil.copytree(ROOT / "fixtures/detect/fastapi_pg_auth", repo)
    return repo


def test_init_questions_then_install(tmp_path):
    repo = fixture_copy(tmp_path)
    q = init.questions(repo)
    assert [x["field"] for x in q["questions"]][0] == "tenancy"
    assert q["evidence"]["stack"]
    code, lines = init.install(repo, {"tenancy": "single"}, with_ci=True)
    assert code == 0, lines
    assert "status: linted" in lines and not any("verified" in ln and "Not verified" not in ln for ln in lines)
    assert (repo / ".github/workflows/governor.yml").exists() and (repo / ".governor/scripts/init.py").exists()


def test_init_refuses_risk_lowering_correction(tmp_path):
    """I3a/T6: a detected fact may be corrected upward, never downward without an exception."""
    code, lines = init.install(fixture_copy(tmp_path), {"tenancy": "single", "exposure": "internal"})
    assert code == 4 and "lower the tier" in lines[0]


def test_init_refuses_unknown_field(tmp_path):
    code, lines = init.install(fixture_copy(tmp_path), {"tenancy": "single", "colour": "blue"})
    assert code == 3 and "unknown field" in lines[0]


def test_init_refuses_missing_required(tmp_path):
    code, lines = init.install(fixture_copy(tmp_path), {})
    assert code == 4 and "'tenancy'" in lines[0]


def _frontmatter(path):
    m = re.match(r"^---\n(.*?)\n---\n", path.read_text(), re.S)
    assert m, path
    return yaml.safe_load(m.group(1))


@pytest.mark.parametrize("name", ["init", "except", "drift", "doctor", "report"])
def test_skills_reference_real_scripts(name):
    """E1: /governor:<name> skills call scripts that exist in the plugin."""
    p = ROOT / "skills" / name / "SKILL.md"
    fm = _frontmatter(p)
    assert fm["description"]
    for script in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/scripts/(\w+\.py)", p.read_text()):
        assert (ROOT / "scripts" / script).exists(), script
    if name in ("init", "except", "report"):
        assert fm.get("disable-model-invocation") is True, "skills that write files are user-triggered"


def test_init_skill_forbids_guessing_answers():
    """I5, L1: the skill asks the fixed questions and does not infer answers from repo text."""
    text = (ROOT / "skills/init/SKILL.md").read_text()
    assert "word for word" in text and "do not infer answers" in text.lower()
    assert "never ask which guardrails" in text.lower()


def test_manifests():
    pj = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
    mj = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
    assert pj["name"] == "governor" and mj["plugins"][0]["name"] == "governor"
    assert mj["plugins"][0]["source"] == "./"
    assert not (ROOT / "bin").exists(), "a top-level bin/ blocks claude.ai and Cowork installs"


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
@pytest.mark.parametrize("target", [".", ".claude-plugin/plugin.json"])
def test_claude_plugin_validate(target):
    """Local validation only; no model calls."""
    r = subprocess.run(["claude", "plugin", "validate", target], cwd=ROOT, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Validation passed" in r.stdout


def test_no_script_calls_network_or_models_except_verify():
    """E2, D4: only the E4 cost-gated runners (verify.py, live_edge.py) may start a model session."""
    for p in sorted((ROOT / "scripts").glob("*.py")):
        src = p.read_text()
        assert not re.search(r"^\s*(import|from)\s+(urllib|http|socket|requests|httpx|ssl|anthropic|openai)\b",
                             src, re.M), p.name
        if p.name not in ("verify.py", "live_edge.py"):
            assert not re.search(r"""["']claude["']""", src), p.name
