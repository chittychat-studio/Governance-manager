"""Vibe-coder readiness: every stack gets a pack, no PyYAML at runtime, plain questions and messages,
uninstall, status and friction (SPEC P1a, P11, P12, E8, I1e, I5b, U1, S1, EV4)."""
import datetime
import json
import os
import subprocess
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import ask  # noqa: E402
import friction  # noqa: E402
import governance  # noqa: E402
import init  # noqa: E402
import lint  # noqa: E402
import packs  # noqa: E402
import remove  # noqa: E402
import status  # noqa: E402

NEXT_SUPABASE = {"package.json": json.dumps({"dependencies": {"next": "14", "react": "18",
                                                             "@supabase/supabase-js": "2"},
                                             "scripts": {"test": "vitest"}})}


def repo_with(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def installed(tmp_path, files=NEXT_SUPABASE, answers=None):
    r = repo_with(tmp_path, files)
    code, lines = init.install(r, answers or {"data_classes": ["pii"], "exposure": "public", "tenancy": "single"},
                               host="claude-code")
    assert code == 0, lines
    return r


def test_runtime_needs_no_pyyaml(tmp_path):
    """E8: a full install, lint, status and remove run with PyYAML made unimportable."""
    repo_with(tmp_path, NEXT_SUPABASE)
    (tmp_path / "a.json").write_text(json.dumps({"data_classes": ["pii"], "exposure": "public", "tenancy": "multi"}))
    prelude = "import sys; sys.modules['yaml'] = None; sys.argv = sys.argv[1:]; import runpy; "
    for script, args in (("init.py", [str(tmp_path), "--answers", str(tmp_path / "a.json"), "--host", "claude-code"]),
                         ("lint.py", [str(tmp_path)]), ("status.py", [str(tmp_path)]), ("drift.py", [str(tmp_path)]),
                         ("remove.py", [str(tmp_path)])):
        r = subprocess.run([sys.executable, "-c", prelude + f"runpy.run_path({str(ROOT / 'scripts' / script)!r}, "
                            "run_name='__main__')", script, *args], capture_output=True, text=True)
        assert r.returncode == 0, (script, r.stdout[-500:], r.stderr[-800:])


def test_next_supabase_gets_node_pack_with_plain_text(tmp_path):
    r = installed(tmp_path)
    gov = governance.read(r)
    assert gov["packs"]["claude-code"]["pack_id"] == "tier3/node/claude-code"
    assert "P11-supabase-rls" in (r / ".claude/rules/governor.md").read_text()
    cfg = json.loads((r / ".claude/hooks/governor_config.json").read_text())
    assert cfg["plain"]["P6-rm-rf"]["you_can"]


def test_enforced_rule_without_plain_text_is_refused():
    data = {"id": "x", "rules": [{"id": "R", "spec": "P6", "text": "t", "enforcement": "enforced",
                                  "mechanism": ["hook"], "agents": ["claude-code"]}]}
    with pytest.raises(packs.PackError, match="P12"):
        packs.validate_pack(data, "x")


@pytest.mark.parametrize("field,raw,want", [("exposure", "not sure", "public"), ("tenancy", "idk", "multi"),
                                            ("app_type", "unsure", "fullstack"), ("stack", "javascript", "node"),
                                            ("stack", "Python", "python"), ("data_classes", ["payments", "not sure"],
                                                                            ["payments", "pii"])])
def test_not_sure_and_plain_words(field, raw, want):
    assumed = []
    got = ask.parse_answer(field, raw, assumed)
    assert (sorted(got) if isinstance(got, list) else got) == want


def test_not_sure_correction_keeps_detected_classes():
    out, _ = ask.apply_corrections({"data_classes": ["payments"]}, {"data_classes": "not sure"}, [])
    assert out["data_classes"] == ["payments", "pii"]


def test_every_question_option_has_plain_help():
    for field in ("app_type", "data_classes", "exposure", "tenancy"):
        from intake import enum_for
        assert set(enum_for(field)) <= set(ask.OPTION_HELP[field]), field


def test_remove_dry_run_changes_nothing(tmp_path):
    r = installed(tmp_path)
    before = {p: p.read_bytes() for p in r.rglob("*") if p.is_file()}
    assert remove.main([str(r)]) == 0
    assert before == {p: p.read_bytes() for p in r.rglob("*") if p.is_file()}


def test_remove_keeps_user_entries_and_text(tmp_path):
    r = repo_with(tmp_path, {**NEXT_SUPABASE, "CLAUDE.md": "# mine\n",
                             ".claude/settings.json": json.dumps({"permissions": {"deny": ["Read(./x)"]},
                                                                  "hooks": {"Stop": [{"hooks": [
                                                                      {"type": "command", "command": "echo hi"}]}]}})})
    installed(tmp_path)
    assert remove.main([str(r), "--yes"]) == 0
    data = json.loads((r / ".claude/settings.json").read_text())
    assert data == {"permissions": {"deny": ["Read(./x)"]},
                    "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}
    assert (r / "CLAUDE.md").read_text() == "# mine\n"
    assert not (r / ".claude/hooks").exists() and not (r / ".claude/governor").exists()
    assert (r / "governance.yaml").exists()


def test_remove_deletes_files_governor_created_and_purges(tmp_path):
    r = installed(tmp_path)
    assert remove.main([str(r), "--yes", "--purge"]) == 0
    assert sorted(p.relative_to(r).as_posix() for p in r.rglob("*") if p.is_file()) == ["package.json"]


def test_reinstall_after_remove_lints(tmp_path):
    r = installed(tmp_path)
    remove.main([str(r), "--yes"])
    installed(tmp_path)
    assert lint.lint(r)[0] == []


def test_status_is_plain_and_honest(tmp_path):
    r = installed(tmp_path)
    lines, code = status.build(r)
    text = "\n".join(lines)
    assert code == 0 and "Governor is on. Tier 3" in text
    assert "blocked from" in text and "ask you first" in text and "not enforced" in text
    assert "hash-pinned, not signed" in text or "signed (verified)" in text
    lines, code = status.build(tmp_path / "nowhere")
    assert code == 1 and "not installed" in lines[0]


def test_friction_counts_from_log(tmp_path):
    log = tmp_path / ".claude/governor/governor.log"
    log.parent.mkdir(parents=True)
    now = datetime.datetime(2026, 9, 29, 12, tzinfo=datetime.timezone.utc)
    old = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    t = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    log.write_text(f"{t} PreToolUse deny P6-rm-rf tool=Bash\n{t} PreToolUse ask P10-dependency-add tool=Bash\n"
                   f"{t} Stop stop_tests block rule=P6-stop-tests\n{t} PostToolUse secret_scan ran rule=P6-secret-scan hits=0\n"
                   f"{t} PostToolUse secret_scan ran rule=P6-secret-scan hits=2\n{old} PreToolUse deny P6-rm-rf tool=Bash\n")
    assert friction.counts(tmp_path, 14, now) == {"P6-rm-rf": {"deny": 1, "ask": 0},
                                                 "P10-dependency-add": {"deny": 0, "ask": 1},
                                                 "P6-stop-tests": {"deny": 1, "ask": 0},
                                                 "P6-secret-scan": {"deny": 1, "ask": 0}}


def test_block_message_is_plain(tmp_path):
    r = installed(tmp_path)
    ev = {"tool_name": "Bash", "cwd": str(r), "tool_input": {"command": "rm -rf app"}}
    res = subprocess.run([sys.executable, str(r / ".claude/hooks/governor_pretool.py")], input=json.dumps(ev),
                         capture_output=True, text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(r)})
    assert res.returncode == 2 and "Why: This deletes a whole folder" in res.stderr and "What you can do:" in res.stderr


def test_python_version_message_is_plain():
    text = (ROOT / "scripts" / "intake.py").read_text()
    assert "python.org/downloads" in text and "Add python.exe to PATH" in text
