"""Shared helpers for Governor hooks (SPEC P5: stdlib only, P6, P7).

Fail closed: callers treat any exception as a block.
"""
import datetime
import fnmatch
import json
import os
import re
import shlex
from pathlib import Path

HERE = Path(__file__).resolve().parent
WRAPPERS = {"sudo", "env", "nohup", "time", "command", "exec", "xargs", "nice", "stdbuf", "timeout"}
SHELLS = {"sh", "bash", "zsh", "dash"}


def load_config():
    """Hook config rendered by Governor (R2)."""
    return json.loads((HERE / "governor_config.json").read_text(encoding="utf-8"))


def project_dir(event):
    """Project root: $CLAUDE_PROJECT_DIR, else the event cwd."""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd())


def gov_dir(event):
    d = project_dir(event) / ".claude" / "governor"
    (d / "state").mkdir(parents=True, exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text("governor.log\nstate/\n", encoding="utf-8")
    return d


def log(event, line):
    """Append one line to .claude/governor/governor.log. Never file content or commands (P6, TM1)."""
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(gov_dir(event) / "governor.log", "a", encoding="utf-8") as fh:
        fh.write(f"{ts} {event.get('hook_event_name', '?')} {line}\n")


def state_path(event, name):
    sid = re.sub(r"[^A-Za-z0-9_-]", "_", str(event.get("session_id") or "nosession"))
    return gov_dir(event) / "state" / f"{sid}.{name}.json"


def read_state(event, name, default):
    p = state_path(event, name)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_state(event, name, value):
    state_path(event, name).write_text(json.dumps(value), encoding="utf-8")


def _split_compound(cmd):
    # Split on shell separators; over-splitting inside quotes only makes matching stricter.
    return [p.strip() for p in re.split(r"&&|\|\||;|\||\n|`|\$\(", cmd) if p.strip()]


def _normalise_one(seg, depth):
    try:
        toks = shlex.split(seg, posix=True)
    except ValueError:
        toks = seg.split()
    while toks and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", toks[0]):
        toks.pop(0)
    last = None
    while toks and os.path.basename(toks[0]) in WRAPPERS:
        last = os.path.basename(toks.pop(0))
        while toks and (toks[0].startswith("-") or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", toks[0])
                        or re.fullmatch(r"\d+[smhd]?", toks[0])):
            toks.pop(0)
    if not toks:
        return [last] if last else []
    toks[0] = os.path.basename(toks[0])
    if toks[0] in SHELLS and "-c" in toks[1:] and depth < 3:
        inner = toks[toks.index("-c", 1) + 1] if toks.index("-c", 1) + 1 < len(toks) else ""
        return normalise(inner, depth + 1)
    if toks[0] == "git":
        rest, i = [], 1
        while i < len(toks):
            if toks[i] in ("-C", "-c", "--git-dir", "--work-tree") and i + 1 < len(toks):
                i += 2
                continue
            rest.append(toks[i])
            i += 1
        toks = ["git"] + rest
    return [" ".join(toks)]


def normalise(cmd, depth=0):
    """Normalise a Bash command into simple segments: wrappers, paths, sh -c and git -C removed (P7)."""
    out = []
    for seg in _split_compound(cmd):
        out.extend(_normalise_one(seg, depth))
    return out


def _variants(path, root):
    p = str(path)
    home = os.path.expanduser("~")
    variants = {p, os.path.basename(p)}
    try:
        variants.add(Path(p).resolve().relative_to(Path(root).resolve()).as_posix())
    except (ValueError, OSError):
        pass
    if p.startswith(home):
        variants.add("~" + p[len(home):].replace(os.sep, "/"))
    if p.startswith("~"):
        variants.add(p)
    return variants


def path_matches(path, globs, root):
    """True if path matches any glob by basename, repo-relative path or ~-path."""
    for v in _variants(path, root):
        for g in globs:
            if fnmatch.fnmatch(v, g) or (g.endswith("/*") and v.startswith(g[:-1])):
                return True
    return False


def tool_paths(tool_input):
    """File paths named by a tool call, whatever the field is called."""
    out = []
    for key in ("file_path", "path", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    return out
