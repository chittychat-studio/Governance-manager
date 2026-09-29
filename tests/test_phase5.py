"""Phase 5 tests: DR1, D1-D4."""
import hashlib
import json
import re
import shutil
import subprocess
import sys

import pytest

import ci
import doctor
import drift
import governance
import packs
import render
from ask import build_intake
from conftest import ROOT
from detect import detect

SRC = ROOT / "fixtures" / "detect" / "fastapi_pg_auth"


def installed_copy(tmp_path, answers=None):
    repo = tmp_path / "repo"
    shutil.copytree(SRC, repo)
    intake = build_intake(detect(repo)["detected"], answers or {"tenancy": "single"})
    governance.write(repo, governance.build(intake))
    render.render(repo)
    return repo


def test_no_drift_after_install(tmp_path):
    repo = installed_copy(tmp_path)
    res = drift.check(repo)
    assert res["failures"] == [], res
    assert drift.main([str(repo)]) == 0


def test_adding_a_data_class_fails(tmp_path):
    """BUILD_PLAN Phase 5 exit / D2a: a PR that adds a data class fails the check."""
    repo = installed_copy(tmp_path)
    (repo / "requirements.txt").write_text((repo / "requirements.txt").read_text() + "stripe\n")
    res = drift.check(repo)
    assert any(f.startswith("D2a") and "payments" in f for f in res["failures"])
    assert drift.main([str(repo)]) == 1


def test_tier_increase_fails(tmp_path):
    """D2: installed as internal (tier 2); repo now has public hosting config -> tier 3."""
    repo = installed_copy(tmp_path, {"tenancy": "single", "exposure": "internal"})
    (repo / "fly.toml").unlink()
    gov = governance.read(repo)
    gov["intake"]["exposure"] = "internal"
    governance.write(repo, governance.build(gov["intake"]))
    render.render(repo)
    assert drift.check(repo)["failures"] == []
    (repo / "fly.toml").write_text('app = "x"\n')
    fails = drift.check(repo)["failures"]
    assert any(f.startswith("D2:") and "2 -> 3" in f for f in fails)
    assert any("exposure changed" in f for f in fails)


def test_stale_governor_file(tmp_path):
    """D1 stale paths."""
    repo = installed_copy(tmp_path)
    (repo / ".claude/hooks/governor_stop.py").unlink()
    assert any("stale path" in f for f in drift.check(repo)["failures"])


def test_stale_rule_paths_warn(tmp_path):
    repo = installed_copy(tmp_path)
    (repo / ".claude/rules/api.md").write_text("---\npaths:\n  - \"src/api/**/*.ts\"\n---\n# x\n")
    assert any("matches no files" in w for w in drift.check(repo)["warnings"])


def test_pack_pin_change_is_drift(tmp_path, monkeypatch):
    repo = installed_copy(tmp_path)
    lock = packs.read_lock()
    lock["tier1/fastapi-postgres/claude-code"] = "0" * 64
    monkeypatch.setattr(drift, "read_lock", lambda: lock)
    assert any("differs from the installed pin" in f for f in drift.check(repo)["failures"])


def tree_hash(root):
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(p.as_posix().encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def test_doctor_flags_gaps_on_old_repo(tmp_path):
    """BUILD_PLAN Phase 5 exit / DR1: gaps reported by rule id, read-only."""
    repo = tmp_path / "old"
    shutil.copytree(SRC, repo)
    (repo / ".claude").mkdir()
    (repo / ".claude/settings.json").write_text(json.dumps({"permissions": {"deny": ["Bash(rm -rf *)"]}}))
    before = tree_hash(repo)
    rep = doctor.audit(repo)
    assert tree_hash(repo) == before
    assert rep["tier"] == 3 and any("tenancy" in a for a in rep["assumed"])
    for rid in ("P6-secret-read", "P6-stop-tests", "P6-secret-scan", "P9-no-pii-in-logs"):
        assert rid in rep["missing"], rid
    rm = next(f for f in rep["findings"] if f["rule"] == "P6-rm-rf")
    assert not rm["ok"] and any("PreToolUse" in g for g in rm["gaps"])
    assert doctor.main([str(repo)]) == 1


def test_doctor_clean_after_install(tmp_path):
    repo = installed_copy(tmp_path)
    ans = tmp_path / "a.json"
    ans.write_text(json.dumps({"tenancy": "single"}))
    rep = doctor.audit(repo, {"tenancy": "single"})
    assert rep["missing"] == [], rep["findings"]
    assert doctor.main([str(repo), "--answers", str(ans)]) == 0


def test_doctor_cannot_audit_unknown_stack(tmp_path):
    shutil.copytree(ROOT / "fixtures/detect/react_vite_static", tmp_path / "r")
    assert doctor.main([str(tmp_path / "r")]) == 2


def test_ci_install_runs_vendored_lint_and_drift(tmp_path):
    """D3: vendored runtime runs lint + drift inside the target repo."""
    repo = installed_copy(tmp_path)
    ci.install(repo)
    for script in ("lint.py", "drift.py"):
        r = subprocess.run([sys.executable, f".governor/scripts/{script}", "."], cwd=repo,
                           capture_output=True, text=True)
        assert r.returncode == 0, (script, r.stdout, r.stderr)
    (repo / "requirements.txt").write_text((repo / "requirements.txt").read_text() + "stripe\n")
    r = subprocess.run([sys.executable, ".governor/scripts/drift.py", "."], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 1 and "D2a" in r.stdout


@pytest.mark.parametrize("wf", [ROOT / "templates/github/governor.yml", ROOT / ".github/workflows/ci.yml"])
def test_workflows_make_no_model_calls(wf):
    """D4."""
    text = wf.read_text().lower()
    assert not re.search(r"\bclaude\b(?!\s*code)|anthropic|openai|secrets\.|verify\.py", text), wf
