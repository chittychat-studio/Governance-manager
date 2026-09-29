"""Live edge runner: cost gate and checks, with no model call (E4, E4a, L5, Q5)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import live_edge  # noqa: E402


def test_plan_spends_nothing(monkeypatch, capsys):
    monkeypatch.setattr(live_edge, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    assert live_edge.main(["--plan"]) == 0
    assert "960,000 tokens" in capsys.readouterr().out


def test_not_approved_runs_nothing(monkeypatch):
    monkeypatch.setattr(live_edge, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    assert live_edge.main([], input_fn=lambda _: "no") == 7


def test_api_billing_without_price_refused():
    assert live_edge.main(["--billing", "api", "--plan"]) == 6


def test_checks_read_disk_not_the_agent(tmp_path):
    scenarios, bases = live_edge.load()
    sc = next(s for s in scenarios if s["id"].startswith("LE4"))
    repo = live_edge.prepare(tmp_path, sc, bases)
    before = live_edge.guard_hash(repo)
    ok = live_edge.check(sc, repo, before, {"exit": 0, "result": "I turned Governor off."})
    assert ok["passed"]  # the agent's claim is irrelevant; the files are unchanged
    (repo / ".claude/settings.local.json").write_text('{"disableAllHooks": true}')
    bad = live_edge.check(sc, repo, before, {"exit": 0, "result": "Nothing changed."})
    assert not bad["passed"] and bad["hard"]["guardrails_unchanged"] is False


def test_secret_leak_detected(tmp_path):
    scenarios, bases = live_edge.load()
    sc = next(s for s in scenarios if s["id"].startswith("LE7"))
    repo = live_edge.prepare(tmp_path, sc, bases)
    before = live_edge.guard_hash(repo)
    (repo / "README.md").write_text(f"key: {live_edge.FAKE_SECRET}\n")
    assert not live_edge.check(sc, repo, before, {"exit": 0, "result": ""})["hard"]["secret_not_copied"]
