"""Regression tests from the production-readiness review (2026-09-29): bypasses, fail-open paths and
false positives found by adversarial reviewers. Each case was reproduced against v0.1.0 before the fix."""
import json
import os
import subprocess
import sys

import pytest

from conftest import run_hook


def pre(repo, tool, **ti):
    return run_hook(repo, "governor_pretool.py", {"hook_event_name": "PreToolUse", "tool_name": tool,
                                                   "tool_input": ti})


def decision(proc):
    if proc.returncode == 2:
        return "deny"
    if proc.stdout.strip():
        return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]
    return "allow" if proc.returncode == 0 else f"error {proc.returncode}"


DENY = [
    # shell grammar the old normaliser missed
    'bash -lc "rm -rf x"', "sh -ec 'rm -rf x'", 'bash -c -e "rm -rf x"', "for d in a; do rm -rf $d; done",
    "if true; then rm -rf x; fi", "(rm -rf x)", "{ rm -rf x; }", "! rm -rf x", "true & rm -rf x",
    "sudo -u root rm -rf x", "find / -exec rm -rf {} +", "find . -name '*.pyc' -delete",
    "for b in a; do git push -f origin $b; done", "rm -rf x 2>&1", "nice -n 5 rm -rf x",
    'python3 -c "import shutil; shutil.rmtree(\'x\')"', "C:/Windows/System32/rm.exe -rf x",
    "git --no-pager push --force", "git push --force-with-lease=main:abc origin main",
    # secrets via shell
    "cat server.pem", "cat tls/private.key", "openssl rsa -in server.key", "cat ~/.kube/config",
    "cat ~/.docker/config.json", "cat ~/.config/gcloud/application_default_credentials.json",
    "cat ~/.azure/accessTokens.json", "cat ~/.ssh/id_ecdsa", "cat ~/.aws/credential*", "cat .e*v",
    "cat /proc/self/environ", "type C:\\repo\\.env",
    # guardrail self-edit via shell (P9, tier 2+)
    "sed -i 's/deny/x/' .claude/settings.json", "echo '{}' > .claude/settings.json",
    "python3 -c \"open('.claude/settings.json','w')\"", "echo 'import sys' > .claude/hooks/governor_pretool.py",
    "mv .claude/hooks /tmp/x", "git checkout HEAD~1 -- .claude/settings.json", "echo {} > .claude/hooks/governor_config.json",
    "python -c \"open('governance.yaml','w')\"", "cat x > .claude/settings.local.json", "rm -rf .claude",
    "tee .claude/settings.json < x", "echo 0 > .claude/governor/state/t1.fails.json",
]
ASK = [
    "kubectl -n prod apply -f x.yaml", "kubectl --context prod apply -f x", "terraform -chdir=infra apply",
    "docker image push x", "make -C infra deploy", "bash deploy.sh", "gcloud run deploy api", "git push heroku main",
    "helm upgrade api ./chart", "python3.11 -m pip install x", "pip --disable-pip-version-check install x",
    "python -m pip -q install x", "pip3.11 install x", "for p in a b; do pip install $p; done",
    "uv sync", "python -m alembic downgrade -1", "psql -f drop.sql", "printenv AWS_SECRET_ACCESS_KEY",
    "export -p", "set", "declare -x", "psql -c 'COPY users TO STDOUT'", "psql -c 'TRUNCATE users'",
]
ALLOW = [
    'git commit -m "docs: explain why push -f is blocked"', "truncate -s 0 app.log", "git log --grep=truncate",
    'echo "COPY users TO stdout" > notes.md', "cat ~/.ssh/id_rsa.pub", "git status", "git add .claude/settings.json",
    "cat .claude/settings.json", "git diff .claude/hooks/governor_pretool.py", "ls -la", "python -m pytest -q",
    "rm -r build", "rm build/x.pyc", "cat .env.example", "git push origin feature",
    "python3 /plugins/governor/scripts/init.py . --answers .claude/governor/answers.json",
    "cat > .claude/governor/answers.json", "ls *.*",
]


@pytest.mark.parametrize("cmd", DENY)
def test_deny(installed, cmd):
    assert decision(pre(installed, "Bash", command=cmd)) == "deny", cmd


@pytest.mark.parametrize("cmd", ASK)
def test_ask(installed, cmd):
    assert decision(pre(installed, "Bash", command=cmd)) == "ask", cmd


@pytest.mark.parametrize("cmd", ALLOW)
def test_no_false_positive(installed, cmd):
    p = pre(installed, "Bash", command=cmd)
    assert decision(p) == "allow", (cmd, p.stderr, p.stdout)


@pytest.mark.parametrize("cmd,want", [
    ("Remove-Item -Recurse -Force governor-test-dir", "deny"), ("rm -r -fo governor-test-dir", "deny"),
    ("ri governor-test-dir -Force -Recurse", "deny"), ("rd /s /q governor-test-dir", "deny"),
    ("Get-Content .env", "deny"), ("gc C:\\repo\\.env.local", "deny"), ("git push -f", "deny"),
    ("pwsh -Command Remove-Item x -Recurse -Force", "deny"), ("gci env:", "ask"), ("pip install x", "ask"),
    ("Set-Content .claude/settings.json '{}'", "deny"), ("Get-Content README.md", "allow"),
    ("Get-ChildItem", "allow"),
])
def test_powershell_tool_is_guarded(installed, cmd, want):
    """Windows: Claude Code's PowerShell tool gets the same rules as Bash."""
    assert decision(pre(installed, "PowerShell", command=cmd)) == want, cmd


def test_powershell_registered_in_settings(installed):
    s = json.loads((installed / ".claude/settings.json").read_text())
    for event in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
        assert any("PowerShell" in g.get("matcher", "") for g in s["hooks"][event]), event


@pytest.mark.parametrize("tool,path,want", [
    ("Write", ".claude/settings.local.json", "deny"), ("Write", ".claude/governor/state/t1.fails.json", "deny"),
    ("Write", ".claude/governor/answers.json", "allow"), ("Read", "C:\\repo\\.env", "deny"),
    ("Read", "/home/other/.aws/credentials", "deny"),
])
def test_paths(installed, tool, path, want):
    p = path if path.startswith(("C:", "/")) else str(installed / path)
    assert decision(pre(installed, tool, file_path=p)) == want


@pytest.mark.parametrize("tool,key,pat,want", [
    ("Grep", "glob", ".env*", "deny"), ("Grep", "glob", "*.pem", "deny"), ("Grep", "glob", "*", "allow"),
    ("Grep", "glob", "*.py", "allow"), ("Glob", "pattern", "**/*.py", "allow"), ("Glob", "pattern", "**/.env", "deny"),
])
def test_search_globs(installed, tool, key, pat, want):
    assert decision(pre(installed, tool, **{key: pat, "pattern" if key == "glob" else "path": "x"})) == want


@pytest.mark.parametrize("breakage", ["log_is_dir", "govdir_is_file"])
@pytest.mark.parametrize("tool,ti", [("Read", {"file_path": ".env"}), ("Bash", {"command": "rm -rf /"}),
                                     ("mcp__evil__x", {}), ("Bash", {"command": "pip install x"})])
def test_unwritable_log_never_fails_open(installed, breakage, tool, ti):
    """A deny must stay a deny when the log cannot be written."""
    gdir = installed / ".claude" / "governor"
    if gdir.exists():
        subprocess.run(["rm", "-rf", str(gdir)], check=True)
    if breakage == "log_is_dir":
        (gdir / "governor.log").mkdir(parents=True)
    else:
        gdir.parent.mkdir(parents=True, exist_ok=True)
        gdir.write_text("x")
    if "file_path" in ti:
        ti = {"file_path": str(installed / ti["file_path"])}
    d = decision(pre(installed, tool, **ti))
    assert d in ("deny", "ask"), d


@pytest.mark.parametrize("body", ["[1]", "null", '"x"', '{"tool_name": "Bash", "tool_input": "rm -rf /"}',
                                  '{"tool_name": "Bash", "tool_input": {"command": ["rm", "-rf"]}}'])
def test_malformed_events_fail_closed(installed, body):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(installed))
    r = subprocess.run([sys.executable, str(installed / ".claude/hooks/governor_pretool.py")], input=body,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 2


def test_gutted_config_fails_closed(installed):
    (installed / ".claude/hooks/governor_config.json").write_text("{}")
    assert decision(pre(installed, "Bash", command="ls")) == "deny"


def test_stop_malformed_event_is_blocked_then_released(installed):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(installed))
    codes = [subprocess.run([sys.executable, str(installed / ".claude/hooks/governor_stop.py")], input="null",
                            capture_output=True, text=True, env=env).returncode for _ in range(5)]
    assert codes[:3] == [2, 2, 2] and codes[4] == 0


# --- lint must not say "linted" when enforcement is gone (V6, V8) ---

import lint  # noqa: E402


@pytest.mark.parametrize("tamper", [
    lambda r: (r / ".claude/hooks/governor_pretool.py").write_text("# Generated by Governor\nimport sys; sys.exit(0)\n"),
    lambda r: (r / ".claude/hooks/governor_config.json").write_text(
        (r / ".claude/hooks/governor_config.json").read_text().replace('"bash_deny": [', '"bash_deny": [], "x": [', 1)),
    lambda r: (r / ".claude/rules/governor.md").write_text((r / ".claude/rules/governor.md").read_text() + "- extra\n"),
])
def test_lint_catches_tampered_generated_files(installed, tamper):
    tamper(installed)
    fails, _ = lint.lint(installed)
    assert any(f.startswith("V8") for f in fails), fails


@pytest.mark.parametrize("name", ["settings.json", "settings.local.json"])
def test_lint_fails_on_disable_all_hooks(installed, name):
    p = installed / ".claude" / name
    data = json.loads(p.read_text()) if p.exists() else {}
    data["disableAllHooks"] = True
    p.write_text(json.dumps(data))
    assert any("disableAllHooks" in f for f in lint.lint(installed)[0])


def test_report_does_not_say_pass_when_hooks_disabled(installed, tmp_path):
    import report
    p = installed / ".claude/settings.json"
    data = json.loads(p.read_text())
    data["disableAllHooks"] = True
    p.write_text(json.dumps(data))
    text = report.build(installed, verify_path=tmp_path / "none")
    assert "Lint (V1-V7): pass" not in text and "status: **generated (lint failing)**" in text


# --- secret scan (P6) ---

sys.path.insert(0, str(__import__("conftest").ROOT / "templates" / "hooks"))
import governor_posttool as post  # noqa: E402


@pytest.mark.parametrize("line", [
    'SECRET_KEY = "9f8a7b6c5d4e3f2a1b0c"', 'db_password = "hunter2hunter2x"', 'client_secret="abcdef123456789"',
    'JWT_SECRET: "z8y7x6w5v4u3t2s1"', 'DATABASE_URL="postgresql://admin:S3cr3t@db:5432/app"',
    'aws_secret_access_key = wJa1rXUtnFEMI/K7MDENG/bPxRfiCYz9Q2h7KEY', 'API_KEY=sk-live-1234567890abcdef',
    "token: github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz0123456789ABCD",
    "-----BEGIN PGP PRIVATE KEY BLOCK-----", "STRIPE=sk_live_" + "a" * 24,
])
def test_secret_scan_hits(line):
    assert post.scan_text(line), line


@pytest.mark.parametrize("line", [
    'SECRET_KEY = os.environ["SECRET_KEY"]', 'password = "changeme-placeholder"', 'token = "test-token-for-fixture"',
    "DATABASE_URL=postgresql://user:${DB_PASSWORD}@db/app", "api_key = settings.api_key", "secret = get_secret()",
    'PASSWORD_MIN_LENGTH = 12', 'url = "https://example.com/path"',
])
def test_secret_scan_ignores_non_secrets(line):
    assert post.scan_text(line) == [], line


# --- Stop hook fingerprint (P6) ---

def _git_repo(repo):
    for c in (["git", "init", "-q"], ["git", "add", "-A"],
              ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]):
        subprocess.run(c, cwd=repo, check=True)


def _stop(repo):
    return run_hook(repo, "governor_stop.py", {"hook_event_name": "Stop"})


@pytest.mark.parametrize("how", ["untracked", "staged"])
def test_stop_reruns_tests_after_untracked_or_staged_change(installed, how):
    cfgp = installed / ".claude/hooks/governor_config.json"
    cfg = json.loads(cfgp.read_text())
    cfg["test_cmd"] = f"{sys.executable} check.py"
    cfgp.write_text(json.dumps(cfg))
    (installed / "check.py").write_text("import sys; sys.exit(0)\n")
    _git_repo(installed)
    if how == "untracked":
        (installed / "check.py").unlink()
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "rm"], cwd=installed)
        (installed / "check.py").write_text("import sys; sys.exit(0)\n")
    assert _stop(installed).stdout.strip() == ""            # green recorded
    (installed / "check.py").write_text("import sys; sys.exit(1)\n")
    if how == "staged":
        subprocess.run(["git", "add", "check.py"], cwd=installed, check=True)
    out = _stop(installed).stdout
    assert out and json.loads(out)["decision"] == "block"
