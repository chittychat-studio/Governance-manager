"""Phase 1 tests: I1–I5, I1a, I5a."""
import json
import re

import pytest

import ask
import detect
import intake
from conftest import ROOT

FIX = ROOT / "fixtures" / "detect"
EXPECTED = {
    "fastapi_pg_auth": {"app_type": "api", "stack": "fastapi-postgres", "data_classes": ["auth", "pii"],
                        "exposure": "public", "agent": ["claude-code"], "test_cmd": "python -m pytest"},
    "react_vite_static": {"app_type": "web-spa", "stack": "react-vite", "exposure": "public",
                          "agent": ["codex"], "test_cmd": "npm test"},
    "node_stripe": {"app_type": "api", "stack": "node-express-postgres",
                    "data_classes": ["auth", "payments", "pii"], "tenancy": "multi", "test_cmd": "pnpm test"},
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_detect_fills_at_least_four_required_fields(name):
    """BUILD_PLAN Phase 1 exit check: ≥4 required fields on each synthetic fixture (I3)."""
    r = detect.detect(FIX / name)
    filled = [f for f in intake.REQUIRED if f in r["detected"]]
    assert len(filled) >= 4, filled
    for k, v in EXPECTED[name].items():
        assert r["detected"][k] == v, k


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_detected_field_has_evidence(name):
    """Evidence-only: nothing is filled without a recorded reason (I3)."""
    r = detect.detect(FIX / name)
    for field in r["detected"]:
        assert r["evidence"].get(field), field


def test_absence_is_unknown_not_a_default(tmp_path):
    """An empty repo detects nothing; no field defaults to a permissive value (I1a, I3)."""
    r = detect.detect(tmp_path)
    assert r["detected"] == {}
    assert set(intake.REQUIRED) <= set(r["unknown"])


def test_schema_required_matches_code():
    """intake.schema.json is the single source for required fields (I1)."""
    assert intake.load_schema()["required"] == intake.REQUIRED


def test_enums_are_closed():
    """I1a enums."""
    assert intake.enum_for("data_classes") == ["none", "pii", "auth", "payments", "health"]
    assert intake.enum_for("exposure") == ["public", "internal"]
    assert intake.enum_for("tenancy") == ["single", "multi"]
    assert intake.enum_for("agent") == ["claude-code", "codex"]


def test_unknown_enum_value_refused():
    """A value outside the enum is refused, never mapped to tier 1 (I1a)."""
    with pytest.raises(intake.IntakeError):
        ask.parse_answer("data_classes", "financial")


def test_none_cannot_combine():
    good = dict(EXPECTED["fastapi_pg_auth"], tenancy="single")
    with pytest.raises(intake.IntakeError):
        intake.validate(dict(good, data_classes=["none", "pii"]))


def test_only_unknown_fields_are_asked():
    """I3: detect runs first; only unknown[] is asked."""
    r = detect.detect(FIX / "fastapi_pg_auth")
    asked = []
    out, _ = ask.run(r, lambda f, q: asked.append(f) or {"tenancy": "single"}.get(f))
    assert asked[0] == "tenancy"
    assert "stack" not in asked and "app_type" not in asked
    assert out["tenancy"] == "single"


def test_max_seven_questions_required_first():
    """I4."""
    plan = ask.plan_questions(intake.REQUIRED + intake.OPTIONAL)
    assert len(plan) == 7
    assert plan == intake.REQUIRED


def test_optional_asked_only_with_remaining_budget():
    """I4: optionals fill leftover budget after required."""
    plan = ask.plan_questions(["tenancy", "exposure"] + intake.OPTIONAL)
    assert plan[:2] == ["exposure", "tenancy"]
    assert len(plan) == 7


def test_missing_required_refuses_naming_field():
    """I2: no partial output."""
    r = detect.detect(FIX / "react_vite_static")
    with pytest.raises(intake.IntakeError, match="'data_classes'"):
        ask.run(r, lambda f, q: None)


def test_cli_refusal_writes_nothing(tmp_path):
    """I2 via the CLI: non-zero exit and no intake file."""
    det = tmp_path / "d.json"
    det.write_text(json.dumps(detect.detect(FIX / "react_vite_static")))
    ans = tmp_path / "none.json"
    ans.write_text("{}")
    out = tmp_path / "intake.json"
    assert ask.main([str(det), "--answers", str(ans), "--out", str(out)]) == 3
    assert not out.exists()


def test_cli_success(tmp_path):
    det = tmp_path / "d.json"
    det.write_text(json.dumps(detect.detect(FIX / "node_stripe")))
    ans = tmp_path / "a.json"
    ans.write_text(json.dumps({"exposure": "public", "agent": "claude-code"}))
    out = tmp_path / "intake.json"
    assert ask.main([str(det), "--answers", str(ans), "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["agent"] == ["claude-code"] and data["conventions"]["pkg_mgr"] == "pnpm"


def test_question_bank_is_fixed_and_factual():
    """I5, I5a: every question maps to one intake field and never asks which controls are wanted."""
    fields = set(intake.REQUIRED) | set(intake.OPTIONAL)
    assert set(ask.QUESTION_BANK) == fields
    banned = re.compile(r"guardrail|control|security measure|protect|policy|restrict|block|allow|permission", re.I)
    for field, (_, text) in ask.QUESTION_BANK.items():
        assert not banned.search(text), (field, text)


def test_scripts_make_no_network_imports():
    """E2: deterministic scripts import no network modules."""
    for name in ("detect.py", "ask.py", "intake.py"):
        src = (ROOT / "scripts" / name).read_text()
        assert not re.search(r"^\s*(import|from)\s+(urllib|http|socket|requests|httpx|ssl)\b", src, re.M), name
