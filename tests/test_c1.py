"""C1/E4: the unattended job cannot spend without an approved cap."""
import c1_budget
import verify
from conftest import ROOT


def test_no_cap_refuses(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text("monthly_cap_usd: null\napproved_by: null\napproved_on: null\n")
    assert c1_budget.per_run_cap(p) is None


def test_cap_needs_approver(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text("monthly_cap_usd: 31\napproved_by: null\napproved_on: 2026-09-29\n")
    assert c1_budget.per_run_cap(p) is None


def test_per_run_cap(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text("monthly_cap_usd: 62\napproved_by: Sandhya\napproved_on: 2026-09-29\n")
    assert c1_budget.per_run_cap(p) == 2.0


def test_shipped_budget_is_unapproved():
    """Nothing is pre-approved in the repo."""
    assert c1_budget.per_run_cap() is None


def test_monthly_ledger(tmp_path):
    """E4/C1a: refuse without a run count, and after 31 runs in the month."""
    p = tmp_path / "b.yaml"
    p.write_text("monthly_cap_usd: 62\napproved_by: Sandhya\napproved_on: 2026-09-29\n")
    assert c1_budget.main([], path=p) == 3
    assert c1_budget.main(["--runs-this-month", "31"], path=p) == 0
    assert c1_budget.main(["--runs-this-month", "32"], path=p) == 3


def test_issue_step_only_on_verify_failure():
    text = (ROOT / ".github/workflows/compat.yml").read_text()
    assert "steps.verify.outcome == 'failure'" in text and "--runs-this-month" in text


def test_verify_cap_requires_api_billing():
    assert verify.main(["--cap-usd", "5", "--plan"]) == 6


def test_verify_refuses_estimate_over_cap(tmp_path, monkeypatch):
    p = tmp_path / "pricing.yaml"
    p.write_text("usd_per_million_tokens_blended: 1000\nsource: https://example.invalid\nchecked: 2099-01-01\n")
    monkeypatch.setattr(verify, "PRICING", p)
    assert verify.main(["--billing", "api", "--cap-usd", "0.01", "--plan"]) == 6


def test_compat_workflow_is_manual_only():
    text = (ROOT / ".github/workflows/compat.yml").read_text()
    on_block = text.split("\non:\n", 1)[1].split("permissions:", 1)[0]
    assert "workflow_dispatch" in on_block and "schedule" not in on_block
    assert "c1_budget.py" in text and "--cap-usd" in text
