#!/usr/bin/env python3
"""Stand-in for `claude -p` used to test verify.py plumbing without spending credits.

It imitates what Claude Code does around tools: calls the rendered PreToolUse hook before a
Bash command and only runs it if allowed, runs PostToolUse after a Write, and runs the Stop
hook at the end. It is not a model and proves nothing about Claude's behaviour.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

repo = Path.cwd()
if "--version" in sys.argv:
    print("0.0.0 (fake)")
    sys.exit(0)
prompt = sys.argv[sys.argv.index("-p") + 1]
hooks = repo / ".claude" / "hooks"
env = dict(os.environ, CLAUDE_PROJECT_DIR=str(repo))


def hook(name, event):
    event = {"session_id": "fake", "cwd": str(repo), **event}
    return subprocess.run([sys.executable, str(hooks / name)], input=json.dumps(event),
                          capture_output=True, text=True, env=env)


def bash(cmd):
    if os.environ.get("FAKE_BYPASS"):          # simulate hooks not firing
        subprocess.run(cmd, shell=True, cwd=repo)
        return
    r = hook("governor_pretool.py", {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                     "tool_input": {"command": cmd}})
    if r.returncode == 2 or '"ask"' in r.stdout:   # headless: ask is not approved
        return
    subprocess.run(cmd, shell=True, cwd=repo)


def write(rel, text):
    (repo / rel).write_text(text)
    hook("governor_posttool.py", {"hook_event_name": "PostToolUse", "tool_name": "Write",
                                  "tool_input": {"file_path": str(repo / rel)}})


if "deploy" in prompt:
    bash("./deploy.sh")
elif "requests" in prompt:
    bash("pip install requests")
elif "profile" in prompt:
    write("app/profile_note.py", "# profile endpoint placeholder\n")
r = hook("governor_stop.py", {"hook_event_name": "Stop"})
print(json.dumps({"result": "fake", "stop_hook": r.stdout.strip()[:200]}))
