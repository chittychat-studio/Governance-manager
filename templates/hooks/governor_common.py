"""Shared helpers for Governor hooks (SPEC P5: stdlib only, P6, P7).

Fail closed: callers treat any exception in a decision as a block. Logging and state writes
never raise, so an unwritable log can never turn a block into an allow.
"""
import datetime
import fnmatch
import json
import os
import re
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHELL_TOOLS = {"Bash", "PowerShell"}
# Wrappers that run the rest of the line as a command, with the flags that take a separate argument.
WRAPPERS = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T", "--user", "--group"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "--unset", "--chdir"},
    "nohup": set(), "time": set(), "command": set(), "exec": set(), "builtin": set(),
    "nice": {"-n", "--adjustment"}, "ionice": {"-c", "-n", "-p"}, "stdbuf": {"-i", "-o", "-e"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "xargs": {"-I", "-n", "-P", "-L", "-d", "-a", "-E", "-s", "--max-args", "--max-procs", "--replace"},
    "chroot": set(), "unbuffer": set(), "script": {"-c"},
}
KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!", "function", "{", "}", "(", ")", "time"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish", "ash", "busybox"}
PWSH = {"pwsh", "powershell", "cmd"}
REQUIRED_CONFIG = ("bash_deny", "bash_ask", "path_deny", "path_deny_write", "test_cmd")
CASE_INSENSITIVE_FS = os.name == "nt" or sys.platform == "darwin"


def load_config():
    """Hook config rendered by Governor (R2). A config missing its keys is refused (fail closed)."""
    cfg = json.loads((HERE / "governor_config.json").read_text(encoding="utf-8"))
    if not isinstance(cfg, dict) or any(k not in cfg for k in REQUIRED_CONFIG):
        raise ValueError("governor_config.json is incomplete; re-run render")
    for k in ("bash_deny", "bash_ask", "path_deny", "path_deny_write"):
        if not isinstance(cfg[k], list):
            raise ValueError(f"governor_config.json: {k} must be a list")
    return cfg


def project_dir(event):
    """Project root: $CLAUDE_PROJECT_DIR, else the event cwd."""
    cwd = event.get("cwd") if isinstance(event, dict) else None
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd())


def gov_dir(event):
    d = project_dir(event) / ".claude" / "governor"
    (d / "state").mkdir(parents=True, exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text("governor.log\nstate/\n", encoding="utf-8")
    return d


def log(event, line):
    """Append one line to .claude/governor/governor.log. Never file content or commands (P6, TM1).
    Never raises: returns False when the log cannot be written."""
    try:
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        name = event.get("hook_event_name", "?") if isinstance(event, dict) else "?"
        with open(gov_dir(event) / "governor.log", "a", encoding="utf-8") as fh:
            fh.write(f"{ts} {name} {line}\n")
        return True
    except Exception:  # noqa: BLE001 - logging must never change a decision
        return False


def session_id(event):
    sid = event.get("session_id") if isinstance(event, dict) else None
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(sid or "nosession"))[:128]


def state_path(event, name):
    return gov_dir(event) / "state" / f"{session_id(event)}.{name}.json"


def read_state(event, name, default):
    try:
        return json.loads(state_path(event, name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def write_state(event, name, value):
    """Never raises; returns False when state cannot be written."""
    try:
        state_path(event, name).write_text(json.dumps(value), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001
        return False


def _program(tok):
    """Basename of a program token, Windows or POSIX, without .exe/.cmd/.bat."""
    base = re.split(r"[\\/]", tok)[-1]
    return re.sub(r"\.(exe|cmd|bat|com)$", "", base, flags=re.I)


def _split_compound(cmd):
    # Drop redirections that contain '&' before splitting on it (2>&1, &>file).
    cmd = re.sub(r"\d*>&\d*-?|&>>?", " ", cmd)
    # Over-splitting (also inside quotes) only makes matching stricter, never looser.
    parts = re.split(r"&&|\|\||;|\||&|\n|\r|`|\$\(|<\(|>\(|\(|\)|\{|\}", cmd)
    return [p.strip() for p in parts if p.strip()]


def _strip_prefix(toks):
    """Remove env assignments, shell keywords and wrappers (with their option arguments)."""
    last = None
    changed = True
    while toks and changed:
        changed = False
        while toks and (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", toks[0]) or toks[0] in KEYWORDS):
            toks.pop(0)
            changed = True
        if toks and _program(toks[0]) in WRAPPERS:
            last = _program(toks.pop(0))
            argflags = WRAPPERS[last]
            while toks and (toks[0].startswith("-") or re.fullmatch(r"\d+(\.\d+)?[smhd]?", toks[0])):
                flag = toks.pop(0)
                if flag in argflags and toks:
                    toks.pop(0)
            changed = True
    return toks, last


def _inner_script(toks):
    """If toks run a shell with an inline script (bash -lc '...', pwsh -Command ...), return it."""
    prog = _program(toks[0]).lower()
    if prog in SHELLS:
        for i, t in enumerate(toks[1:], 1):
            if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", t):
                rest = [x for x in toks[i + 1:] if not (x.startswith("-") and len(x) > 1)]
                return rest[0] if rest else ""
    if prog in PWSH:
        for i, t in enumerate(toks[1:], 1):
            if t.lower() in ("-c", "-command", "/c", "/k", "-commandwithargs"):
                return " ".join(toks[i + 1:])
    return None


def _normalise_one(seg, depth):
    seg = seg.replace("\\", "/")
    try:
        toks = shlex.split(seg, posix=True)
    except ValueError:
        toks = seg.split()
    toks, last = _strip_prefix(toks)
    if not toks:
        return [last] if last else []
    toks[0] = _program(toks[0])
    if depth < 4:
        inner = _inner_script(toks)
        if inner is not None:
            return [" ".join(toks)] + normalise(inner, depth + 1)
    out = []
    if toks[0] == "git":
        rest, i = [], 1
        while i < len(toks) and toks[i].startswith("-"):
            if toks[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path") and i + 1 < len(toks):
                i += 2
            else:
                i += 1
        toks = ["git"] + toks[i:]
    if toks[0] == "find" and depth < 4:
        for i, t in enumerate(toks):
            if t in ("-exec", "-execdir", "-ok", "-okdir"):
                inner = []
                for x in toks[i + 1:]:
                    if x in (";", "+", "/;"):
                        break
                    inner.append(x)
                out += normalise(" ".join(shlex.quote(x) for x in inner), depth + 1)
    return [" ".join(toks)] + out


def normalise(cmd, depth=0):
    """Normalise a shell command into simple segments (P7): wrappers, keywords, paths, `bash -c`,
    `pwsh -Command`, `find -exec`, `git -C` are unwrapped. The raw command is included too."""
    out = [] if depth else [" ".join(str(cmd).split())]
    for seg in _split_compound(str(cmd)):
        out.extend(_normalise_one(seg, depth))
    return [s for s in out if s]


def fail_key(cmd):
    """Stable key for 'the same command' in the P8 repeat-failure counter."""
    return " && ".join(normalise(cmd)[1:])


def _fold(s):
    s = str(s).replace("\\", "/")
    return s.casefold() if CASE_INSENSITIVE_FS else s


def _variants(path, root):
    p = _fold(path)
    home = _fold(os.path.expanduser("~"))
    variants = {p, p.rsplit("/", 1)[-1]}
    try:
        rel = Path(str(path)).resolve().relative_to(Path(root).resolve()).as_posix()
        variants.add(_fold(rel))
    except (ValueError, OSError):
        pass
    if p.startswith(home):
        variants.add("~" + p[len(home):])
    return variants


def path_matches(path, globs, root):
    """True if path matches any glob by basename, repo-relative path, ~-path or absolute path."""
    for v in _variants(path, root):
        for g in globs:
            g = _fold(g)
            if fnmatch.fnmatch(v, g) or (g.endswith("/*") and v.startswith(g[:-1])):
                return True
    return False


def glob_may_match(user_glob, globs):
    """True if a search glob (Grep glob / Glob pattern) targets a protected file. Bare wildcards
    ('*', '**/*') are left to the Read permission rules, or every directory listing would be blocked."""
    ug = _fold(user_glob).rsplit("/", 1)[-1]
    if not re.search(r"[A-Za-z0-9]", ug.replace("*", "")):
        return False
    for g in globs:
        example = _fold(g).rsplit("/", 1)[-1].replace("*", "x")
        if example and fnmatch.fnmatch(example, ug):
            return True
    return False


def tool_paths(tool_input):
    """File paths named by a tool call, whatever the field is called."""
    out = []
    if not isinstance(tool_input, dict):
        return out
    for key in ("file_path", "path", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    return out
