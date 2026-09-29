"""Phase 3 hook tests: block and allow cases with sample stdin JSON (P5-P10, P7)."""
import json

import pytest

from conftest import ROOT, run_hook


def pre(repo, tool, **ti):
    return run_hook(repo, "governor_pretool.py", {"hook_event_name": "PreToolUse", "tool_name": tool,
                                                   "tool_input": ti})


def decision(proc):
    if proc.returncode == 2:
        return "deny"
    if proc.stdout.strip():
        return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]
    return "allow" if proc.returncode == 0 else f"error {proc.returncode}"


@pytest.mark.parametrize("cmd", [
    "rm -rf build/", "rm -fr /", "rm -r -f x", "rm --recursive --force x", "/bin/rm -rf x",
    "sudo rm -rf /var", "bash -c 'rm -rf build/'", "cd x && rm -rf y", "FOO=1 rm -Rf x",
    "git push --force origin main", "git push -f", "git -C . push --force", "git push origin +main",
    "git -c push.default=current push -f", "cat .env", "less .env.production", "cp ~/.aws/credentials /tmp",
    "cat ~/.ssh/id_rsa",
])
def test_bash_denied(installed, cmd):
    """P6 + P7: variants that plain permission rules miss are blocked by the hook."""
    p = pre(installed, "Bash", command=cmd)
    assert decision(p) == "deny", (cmd, p.stderr)
    assert "Governor rule P6-" in p.stderr


@pytest.mark.parametrize("cmd", [
    "fly deploy", "terraform apply -auto-approve", "kubectl apply -f k8s/", "./deploy.sh prod",
    "npm run deploy", "pg_dump prod > x.sql", "alembic downgrade -1", "psql -c 'DROP TABLE users'",
    "pip install requests", "python -m pip install x", "npm install left-pad", "printenv", "env",
    "claude -p hello", "openai api chat",
])
def test_bash_ask(installed, cmd):
    """P6 prod deploy, P8 paid CLI, P9, P10 -> ask."""
    assert decision(pre(installed, "Bash", command=cmd)) == "ask", cmd


@pytest.mark.parametrize("cmd", [
    "ls -la", "rm build/x.pyc", "rm -r build", "git push origin feature", "cp .env.example .env.local.example",
    "cat .env.example", "python -m pytest", "git status", "echo deployed", "env FOO=1 python app.py",
    "cat ~/.ssh/id_rsa.pub",
])
def test_bash_allowed(installed, cmd):
    """Normal work is not blocked."""
    p = pre(installed, "Bash", command=cmd)
    assert decision(p) == "allow", (cmd, p.stderr, p.stdout)


@pytest.mark.parametrize("tool,path,want", [
    ("Read", ".env", "deny"), ("Read", "config/.env.prod", "deny"), ("Read", "certs/server.pem", "deny"),
    ("Read", "~/.aws/credentials", "deny"), ("Read", ".env.example", "allow"), ("Read", "app/main.py", "allow"),
    ("Edit", ".claude/settings.json", "deny"), ("Write", ".claude/hooks/governor_pretool.py", "deny"),
    ("Edit", "governance.yaml", "deny"), ("Edit", "app/main.py", "allow"), ("Read", "governance.yaml", "allow"),
])
def test_paths(installed, tool, path, want):
    """P6 secret reads, P9 self-edit."""
    key = "file_path"
    abs_path = path if path.startswith("~") else str(installed / path)
    assert decision(pre(installed, tool, **{key: abs_path})) == want, (tool, path)


def test_mcp_allowlist(installed):
    """P6: unlisted MCP server denied."""
    assert decision(pre(installed, "mcp__github__create_issue")) == "deny"


def test_mcp_allowlisted_server_allowed(tmp_path):
    import governance
    import render
    from conftest import FIXTURE_INTAKE
    repo = tmp_path / "r"
    repo.mkdir()
    governance.write(repo, governance.build(FIXTURE_INTAKE, mcp_allow=["github"]))
    render.render(repo)
    assert decision(pre(repo, "mcp__github__create_issue")) == "allow"
    assert decision(pre(repo, "mcp__slack__post")) == "deny"


def test_denials_are_logged_without_content(installed):
    pre(installed, "Bash", command="rm -rf /secret-path-xyz")
    log = (installed / ".claude/governor/governor.log").read_text()
    assert "deny P6-rm-rf" in log and "secret-path-xyz" not in log


def test_broken_config_fails_closed(installed):
    (installed / ".claude/hooks/governor_config.json").write_text("{not json")
    assert pre(installed, "Bash", command="ls").returncode == 2


def post(repo, tool, event_name="PostToolUse", **kw):
    return run_hook(repo, "governor_posttool.py", {"hook_event_name": event_name, "tool_name": tool, **kw})


def test_secret_scan_blocks_and_logs(installed):
    """P6 secret scan: hit -> decision block naming pattern, never the value; always logged."""
    f = installed / "app" / "cfg.py"
    f.parent.mkdir(exist_ok=True)
    f.write_text('AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n')
    p = post(installed, "Write", tool_input={"file_path": str(f)})
    out = json.loads(p.stdout)
    assert out["decision"] == "block" and "aws-access-key" in out["reason"]
    assert "AKIAABCDEFGHIJKLMNOP" not in p.stdout
    assert "secret_scan ran rule=P6-secret-scan hits=1" in (installed / ".claude/governor/governor.log").read_text()


def test_secret_scan_clean_file(installed):
    f = installed / "clean.py"
    f.write_text('API_KEY = os.environ["API_KEY"]\npassword = "changeme-placeholder"\n')
    p = post(installed, "Edit", tool_input={"file_path": str(f)})
    assert p.stdout.strip() == "" and p.returncode == 0
    assert "hits=0" in (installed / ".claude/governor/governor.log").read_text()


def test_repeat_fail_blocks_after_three(installed):
    """P8: same failing command blocked after 3 failures."""
    for _ in range(3):
        assert decision(pre(installed, "Bash", command="make broken")) == "allow"
        post(installed, "Bash", event_name="PostToolUseFailure", tool_input={"command": "make broken"},
             tool_response={"error": "exit 1"})
    p = pre(installed, "Bash", command="make broken")
    assert decision(p) == "deny" and "P8-repeat-fail" in p.stderr
    assert decision(pre(installed, "Bash", command="make other")) == "allow"


def test_repeat_fail_resets_on_success(installed):
    for _ in range(2):
        post(installed, "Bash", event_name="PostToolUseFailure", tool_input={"command": "make x"})
    post(installed, "Bash", tool_input={"command": "make x"}, tool_response={"stdout": "ok"})
    post(installed, "Bash", event_name="PostToolUseFailure", tool_input={"command": "make x"})
    assert decision(pre(installed, "Bash", command="make x")) == "allow"


def stop(repo):
    return run_hook(repo, "governor_stop.py", {"hook_event_name": "Stop"})


def set_test_cmd(repo, cmd):
    cfgp = repo / ".claude/hooks/governor_config.json"
    cfg = json.loads(cfgp.read_text())
    cfg["test_cmd"] = cmd
    cfgp.write_text(json.dumps(cfg))


def test_stop_blocks_on_red_then_loop_guard_releases(installed):
    """P6 stop hook blocks on failing tests; loop guard releases after 3 blocks."""
    set_test_cmd(installed, "exit 1")
    for _ in range(3):
        p = stop(installed)
        assert json.loads(p.stdout)["decision"] == "block"
    p = stop(installed)
    assert p.returncode == 0 and p.stdout.strip() == ""
    log = (installed / ".claude/governor/governor.log").read_text()
    assert log.count("stop_tests block") == 3 and "loop-guard released" in log


def test_stop_allows_on_green(installed):
    set_test_cmd(installed, "exit 0")
    p = stop(installed)
    assert p.returncode == 0 and p.stdout.strip() == ""
    assert "stop_tests pass" in (installed / ".claude/governor/governor.log").read_text()


def test_hook_templates_are_stdlib_only():
    """P5."""
    import ast
    import sys
    allowed = set(sys.stdlib_module_names) | {"governor_common"}
    for p in (ROOT / "templates" / "hooks").glob("*.py"):
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for n in names:
                assert n.split(".")[0] in allowed, (p.name, n)
