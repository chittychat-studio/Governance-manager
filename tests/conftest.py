import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import json as _json
import shutil as _shutil
import subprocess as _subprocess

import pytest as _pytest

FIXTURE_INTAKE = {"app_type": "api", "stack": "fastapi-postgres", "data_classes": ["auth", "pii"],
                  "exposure": "public", "tenancy": "single", "agent": ["claude-code"],
                  "test_cmd": "python -m pytest -q"}


def install(repo, intake=None, settings=None):
    """detect-free install: governance.yaml + render into repo."""
    import governance
    import render
    repo.mkdir(parents=True, exist_ok=True)
    if settings is not None:
        (repo / ".claude").mkdir(exist_ok=True)
        (repo / ".claude" / "settings.json").write_text(_json.dumps(settings))
    governance.write(repo, governance.build(intake or FIXTURE_INTAKE))
    render.render(repo)
    return repo


@_pytest.fixture
def installed(tmp_path):
    return install(tmp_path / "repo")


def run_hook(repo, name, event, env_extra=None):
    """Run a rendered hook with a stdin JSON event; returns CompletedProcess."""
    import os
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(repo), **(env_extra or {}))
    event = {"session_id": "t1", "cwd": str(repo), **event}
    return _subprocess.run([sys.executable, str(repo / ".claude" / "hooks" / name)],
                           input=_json.dumps(event), capture_output=True, text=True, env=env, timeout=60)
