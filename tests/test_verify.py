"""Phase 4 tests: verify.py plumbing (Q1-Q5, E4, E4a) with a stand-in CLI. No credits spent."""
import datetime
import json
import sys

import pytest

import verify
from conftest import ROOT

FAKE = str(ROOT / "tests" / "stub" / "fake_claude.py")
RED_IF_SEEDED = f"{sys.executable} -c \"import pathlib,sys; sys.exit(1 if pathlib.Path('tests/test_seeded_red.py').exists() else 0)\""


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(verify, "ANSWERS", dict(verify.ANSWERS, test_cmd=RED_IF_SEEDED))
    return tmp_path


def test_plan_spends_nothing(sandbox, capsys):
    assert verify.main(["--plan", "--claude", "/nonexistent"]) == 0
    out = capsys.readouterr().out
    assert "Estimate" in out and "Q2.3-deploy" in out
    assert not (sandbox / "results").exists()


def test_approval_required(sandbox):
    """E4: no 'yes' -> nothing runs, nothing written."""
    assert verify.main(["--claude", "/nonexistent"], input_fn=lambda _: "no") == 7
    assert not (sandbox / "results").exists()


def test_api_billing_needs_sourced_price(sandbox, monkeypatch):
    """E4a: no price/source/date -> refuse."""
    monkeypatch.setattr(verify, "PRICING", sandbox / "none.yaml")
    assert verify.main(["--billing", "api", "--plan"]) == 6


def test_api_estimate_and_stale_warning(sandbox, monkeypatch):
    p = sandbox / "pricing.yaml"
    old = (datetime.date.today() - datetime.timedelta(days=120)).isoformat()
    p.write_text(f"usd_per_million_tokens_blended: 10\nsource: https://example.invalid/pricing\nchecked: {old}\n")
    monkeypatch.setattr(verify, "PRICING", p)
    tokens, usd, text = verify.estimate(2, "api")
    assert tokens == 4 * 2 * verify.TOKEN_BUDGET_PER_TASK
    assert usd == pytest.approx(tokens / 1e6 * 10)
    assert "WARNING" in text


def test_end_to_end_with_stub_passes_twice(sandbox):
    """Q1-Q3 plumbing: rendered hooks block deploy, scan runs, Stop refuses on the seeded red test."""
    assert verify.main(["--claude", FAKE, "--approve", "--runs", "2"]) == 0
    res = json.loads((sandbox / "results" / "last.json").read_text())
    assert res["status"] == "verified" and len(res["runs"]) == 2
    assert all(r["checks"] == {"deploy_blocked": True, "secret_scan_ran": True, "stop_hook_refused_red": True}
               for r in res["runs"])
    assert "not any client repo" in res["scope"]


def test_end_to_end_fails_when_hooks_do_not_fire(sandbox, monkeypatch):
    """Q3: if the deploy actually runs, verify fails (Q5: status 'failed', never 'verified')."""
    monkeypatch.setenv("FAKE_BYPASS", "1")
    assert verify.main(["--claude", FAKE, "--approve", "--runs", "1"]) == 1
    res = json.loads((sandbox / "results" / "last.json").read_text())
    assert res["status"] == "failed" and res["runs"][0]["checks"]["deploy_blocked"] is False


def test_red_baseline_refuses(sandbox, monkeypatch):
    """A red fixture baseline would make the Stop check meaningless -> refuse."""
    monkeypatch.setattr(verify, "ANSWERS", dict(verify.ANSWERS, test_cmd="exit 1"))
    with pytest.raises(RuntimeError, match="baseline tests are red"):
        verify.run_once(FAKE)


def test_fixture_is_fastapi_postgres_tier3():
    """Q1: fixture detects as fastapi-postgres with pii + public -> tier 3."""
    import detect
    import tier
    from ask import build_intake
    d = detect.detect(verify.FIXTURE)
    intake = build_intake(d["detected"], verify.ANSWERS)
    assert intake["stack"] == "fastapi-postgres"
    assert tier.compute_tier(intake)[0] == 3
