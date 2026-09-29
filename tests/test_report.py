"""Phase 6 tests: EV1, EV1a, EV2, EV3, X3."""
import datetime
import json

import exceptions
import render
import report

D = datetime.date(2026, 9, 29)


def test_one_page_with_required_parts(installed, tmp_path):
    text = report.build(installed, today=D, verify_path=tmp_path / "none.json")
    assert len(text.splitlines()) <= report.MAX_LINES
    for part in ("## Tier", "Tier 3", "| claude-code | 15 | 2 | 0 |", "## Exceptions", "Lint (V1-V7): pass",
                 "Drift (D1-D2a): none", "not a compliance certificate"):
        assert part in text, part


def test_no_verify_is_stated_not_invented(installed, tmp_path):
    """EV1: never implies verification that did not happen."""
    text = report.build(installed, today=D, verify_path=tmp_path / "none.json")
    assert "not run" in text and "verified on" not in text


def test_verify_result_labelled_as_fixture(installed, tmp_path):
    v = tmp_path / "last.json"
    v.write_text(json.dumps({"status": "verified", "date": "2026-10-01T10:00:00+00:00",
                             "governor_version": "0.1.0", "claude_version": "2.1.284"}))
    text = report.build(installed, today=D, verify_path=v)
    assert "reference fixture (not this repo): verified on 2026-10-01" in text


def test_exceptions_listed_with_reason(installed, tmp_path):
    """X3."""
    exceptions.add(installed, rule="P9-db-dump", reason="Backups run pg_dump by design here.", today=D,
                   user="a@b.c")
    render.render(installed)
    text = report.build(installed, today=D, verify_path=tmp_path / "x")
    assert "P9-db-dump disabled on 2026-09-29 by a@b.c: Backups run pg_dump by design here." in text
    assert "| claude-code | 14 | 2 | 1 |" in text


def test_no_inferred_mappings(installed, tmp_path):
    """EV2: no mapping unless a pack rule declares one."""
    text = report.build(installed, today=D, verify_path=tmp_path / "x")
    assert "None declared" in text and "OWASP" not in text


def test_declared_mapping_is_shown(installed, tmp_path, monkeypatch):
    orig = render.split_rules

    def with_mapping(gov, agent):
        rules, dis = orig(gov, agent)
        return [dict(r, mappings=["OWASP LLM06 Excessive Agency"]) if r["id"] == "P6-rm-rf" else r
                for r in rules], dis
    monkeypatch.setattr(render, "split_rules", with_mapping)
    text = report.build(installed, today=D, verify_path=tmp_path / "x")
    assert "- P6-rm-rf: OWASP LLM06 Excessive Agency" in text


def test_cli_writes_file(installed, tmp_path):
    out = tmp_path / "r.md"
    assert report.main([str(installed), "--out", str(out)]) == 0
    assert out.read_text().startswith("# Governor evidence report")
