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
SHELL_TOOLS = {"Bash", "PowerShell", "Monitor"}   # Monitor runs a shell command too (P9)
# Wrappers that run the rest of the line as a command, with the flags that take a separate argument.
WRAPPERS = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T", "--user", "--group"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "--unset", "--chdir"},
    "nohup": set(), "time": set(), "command": set(), "exec": set(), "builtin": set(),
    "nice": {"-n", "--adjustment"}, "ionice": {"-c", "-n", "-p"}, "stdbuf": {"-i", "-o", "-e"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "xargs": {"-I", "-n", "-P", "-L", "-d", "-a", "-E", "-s", "--max-args", "--max-procs", "--replace"},
    "chroot": set(), "unbuffer": set(), "script": {"-c"}, "busybox": set(), "setsid": set(), "flock": {"-w", "-E"},
    "watch": {"-n", "-d", "--interval"}, "stdbuf": {"-i", "-o", "-e"}, "caffeinate": set(), "doas": {"-u", "-C"},
}
# Wrappers whose first positional argument is not the command (flock LOCKFILE cmd, chroot DIR cmd).
POSITIONAL_WRAPPERS = {"flock": 1, "chroot": 1}
EVALS = {"eval", "iex", "invoke-expression"}
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


def explain(cfg, rule):
    """P12: the plain 'why' and 'what you can do' lines for a rule, or '' when the config has none."""
    info = (cfg.get("plain") or {}).get(rule) if isinstance(cfg.get("plain"), dict) else None
    if not isinstance(info, dict):
        return ""
    return f"\nWhy: {info.get('plain', '')}\nWhat you can do: {info.get('you_can', '')}"


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
    """Split on shell operators outside quotes. Inside double quotes only command substitution ($(, `)
    splits, because it still runs there; single-quoted text is never split."""
    cmd = re.sub(r"\d*>&\d*-?|&>>?", " ", cmd)  # redirections containing '&' (2>&1, &>file)
    parts, cur, quote, i = [], [], None, 0
    ops = ("&&", "||", "$(", "<(", ">(", ";", "|", "&", "\n", "\r", "`", "(", ")", "{", "}")
    while i < len(cmd):
        ch = cmd[i]
        if quote == "'":
            if ch == "'":
                quote = None
            cur.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < len(cmd) and quote != "'":
            cur.append(cmd[i:i + 2])
            i += 2
            continue
        if ch in ("'", '"') and (quote is None or quote == ch):
            quote = None if quote else ch
            cur.append(ch)
            i += 1
            continue
        op = next((o for o in ops if cmd.startswith(o, i)), None)
        if op and (quote is None or op in ("$(", "`")):
            parts.append("".join(cur))
            cur = []
            i += len(op)
            continue
        cur.append(ch)
        i += 1
    parts.append("".join(cur))
    out = [p.strip() for p in parts if p.strip()]
    # Fail closed where quote tracking can be fooled ($'..' escapes, PowerShell backtick escapes, an unterminated
    # quote): also split naively on every operator. Extra segments can only make a rule match, never hide one (P7).
    if quote is not None or "$'" in cmd or "`" in cmd:
        for p in re.split(r"&&|\|\||[;&|\n\r()`{}]", cmd):
            if p.strip() and p.strip() not in out:
                out.append(p.strip())
    return out


def expand_braces(s, limit=16):
    """Expand simple {a,b} groups (bash brace expansion) so `.{env,x}` is seen as `.env`."""
    out = [s]
    for _ in range(4):
        nxt = []
        for x in out:
            m = re.search(r"\{([^{}\s]*,[^{}\s]*)\}", x)
            if not m:
                nxt.append(x)
                continue
            nxt += [x[:m.start()] + alt + x[m.end():] for alt in m.group(1).split(",")]
        out = nxt[:limit]
    return out


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
            for _ in range(POSITIONAL_WRAPPERS.get(last, 0)):
                if toks:
                    toks.pop(0)
            changed = True
    return toks, last


def _inner_script(toks):
    """If toks run a shell with an inline script (bash -lc '...', pwsh -Command ...), return it."""
    prog = _program(toks[0]).lower()
    if prog in EVALS:
        return " ".join(toks[1:])
    if "<<<" in toks[1:] and (prog in SHELLS or prog in PWSH or prog.startswith("python")):
        i = toks.index("<<<")
        return toks[i + 1] if i + 1 < len(toks) else ""
    if prog in ("su", "runuser"):
        for i, t in enumerate(toks[1:], 1):
            if t in ("-c", "--command") and i + 1 < len(toks):
                return toks[i + 1]
        return None
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


# Runners that execute the rest of the line as another command (uv run pytest, docker compose exec db psql).
RUNNERS = {("uv", "run"), ("poetry", "run"), ("pdm", "run"), ("pipenv", "run"), ("hatch", "run"), ("rye", "run"),
           ("pnpm", "exec"), ("pnpm", "dlx"), ("yarn", "dlx"), ("npm", "exec")}
SINGLE_RUNNERS = {"npx", "bunx", "pipx"}
CONTAINER_ARGFLAGS = {"-u", "--user", "-e", "--env", "-w", "--workdir", "--env-file", "--name", "-p", "--publish",
                      "-v", "--volume", "--entrypoint", "--index", "-l", "--label", "--network", "--profile", "-f",
                      "--file", "--project-name", "-c", "--container", "-n", "--namespace", "--context"}


def _runner_inner(toks):
    """If toks run another command through a runner or container, return that command's tokens."""
    prog = toks[0].lower()
    rest = toks[1:]
    if prog in SINGLE_RUNNERS:
        if prog == "pipx" and rest[:1] == ["run"]:
            rest = rest[1:]
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        return rest
    if len(toks) > 1 and (prog, toks[1].lower()) in RUNNERS:
        rest = toks[2:]
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        return rest
    if prog in ("docker", "podman", "kubectl", "oc", "docker-compose"):
        i = 1
        if prog in ("docker", "podman") and i < len(toks) and toks[i] == "compose":
            i += 1
        while i < len(toks) and toks[i].startswith("-"):   # global flags (compose -f x, kubectl -n x)
            i += 2 if toks[i] in CONTAINER_ARGFLAGS else 1
        if i >= len(toks) or toks[i] not in ("exec", "run"):
            return None
        i += 1
        if prog in ("kubectl", "oc"):
            return toks[toks.index("--") + 1:] if "--" in toks[i:] else None
        while i < len(toks) and toks[i].startswith("-"):
            i += 2 if toks[i] in CONTAINER_ARGFLAGS else 1
        return toks[i + 1:] if i + 1 < len(toks) else None   # skip the service/container name
    return None


def _normalise_one(seg, depth, tool="Bash"):
    if tool == "PowerShell":
        seg = seg.replace("\\", "/")   # Windows path separators; PowerShell's escape char is the backtick
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
            return [" ".join(toks)] + normalise(inner, depth + 1, tool)
    out = []
    if depth < 4:
        inner = _runner_inner(toks)
        if inner:
            out += normalise(" ".join(shlex.quote(x) for x in inner), depth + 1, tool)
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
                out += normalise(" ".join(shlex.quote(x) for x in inner), depth + 1, tool)
    return [" ".join(toks)] + out


MANIFEST_SKIP = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", ".next", ".governor",
                 ".claude", ".tox", ".mypy_cache", ".pytest_cache", "site-packages"}


def manifest_digest(root, globs, limit=5000):
    """P10a: hash of every manifest/lock file under root (names matching globs), or None if it cannot be computed.
    Pure filesystem: runs no git (a repo's git config could run code)."""
    import fnmatch
    import hashlib
    h, seen = hashlib.sha256(), 0
    try:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in MANIFEST_SKIP)
            for name in sorted(files):
                seen += 1
                if seen > limit:
                    return None
                if any(fnmatch.fnmatch(name, g) for g in globs):
                    fp = os.path.join(dirpath, name)
                    h.update(os.path.relpath(fp, root).replace("\\", "/").encode() + b"\0")
                    with open(fp, "rb") as fh:
                        h.update(fh.read())
    except OSError:
        return None
    return h.hexdigest()


def manifests_unchanged(event, root, globs):
    """P10a: True only if the manifests are byte-identical to the baseline recorded at this session's first tool call.
    No baseline, an unreadable tree or a state write failure: False (the rule asks)."""
    base = read_state(event, "manifests", None)
    return isinstance(base, str) and base == manifest_digest(root, globs)


def record_manifest_baseline(event, root, globs):
    """Record the session baseline once, at the first tool call Governor sees in a session (P10a)."""
    if read_state(event, "manifests", None) is None:
        d = manifest_digest(root, globs)
        if d:
            write_state(event, "manifests", d)


def strip_comments(cmd):
    """P7b: drop shell comments (# at the start of a word, outside quotes, to end of line), but only when the command
    is plain enough that the result is certain. Backslashes, $'...' quoting, backticks (PowerShell escape, bash
    substitution), heredocs or unbalanced quotes: the command is returned unchanged, so a comment can only make
    a rule match (ask or deny), never hide a command."""
    cmd = str(cmd)
    if "#" not in cmd or any(x in cmd for x in ("\\", "$'", "`", "<<", "${", "$(", "$[")) or \
            cmd.count("'") % 2 or cmd.count('"') % 2:
        return cmd.rstrip()
    out, quote, i = [], None, 0
    while i < len(cmd):
        c = cmd[i]
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c == "#" and (i == 0 or cmd[i - 1] in " \t\n;|&("):
            nl = cmd.find("\n", i)
            if nl < 0:
                break
            i = nl
            continue
        out.append(c)
        i += 1
    if quote:
        return cmd.rstrip()
    return "".join(out).rstrip()


def normalise(cmd, depth=0, tool="Bash"):
    """Normalise a shell command into simple segments (P7): wrappers, keywords, paths, `bash -c`,
    `pwsh -Command`, `eval`, `find -exec`, runners, containers and `git -C` are unwrapped; brace groups are
    expanded; text piped into a bare shell is treated as a script. The raw command is included too."""
    cmd = strip_comments(cmd) if depth == 0 else str(cmd)
    variants = expand_braces(cmd) if depth == 0 else [cmd]
    out = [" ".join(v.split()) for v in variants] if depth == 0 else []
    for v in variants:
        segs = _split_compound(v)
        for seg in segs:
            out.extend(_normalise_one(seg, depth, tool))
        # `echo "rm -rf x" | sh`: a bare shell reading stdin runs what the other segments print.
        if depth < 3 and "|" in v and any(_is_bare_shell(x) for x in segs):
            for seg in segs:
                toks = seg.split(None, 1)
                if toks and _program(toks[0]).lower() in ("echo", "printf", "print", "write-output") and len(toks) > 1:
                    out.extend(normalise(toks[1].strip("'\""), depth + 1, tool))
    return [s for s in out if s]


def _is_bare_shell(seg):
    toks = seg.split()
    return bool(toks) and _program(toks[0]).lower() in SHELLS | PWSH and all(t.startswith("-") for t in toks[1:])


def fail_key(cmd, tool="Bash"):
    """Stable key for 'the same command' in the P8 repeat-failure counter."""
    return " && ".join(normalise(cmd, tool=tool)[1:])


def _fold(s):
    s = str(s).replace("\\", "/")
    return s.casefold() if CASE_INSENSITIVE_FS else s


def _variants(path, root):
    p = _fold(path)
    home = _fold(os.path.expanduser("~"))
    variants = {p, p.rsplit("/", 1)[-1]}
    try:
        pp = Path(str(path))
        pp = pp if pp.is_absolute() or str(path).startswith("~") else Path(root) / pp
        rel = pp.resolve().relative_to(Path(root).resolve()).as_posix()
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


# ---- P9 guardrail guard: shell commands that could change Governor's own files ----------------------------
GUARD_TARGETS = [".claude/settings.json", ".claude/settings.local.json", ".claude/hooks/governor_pretool.py",
                 ".claude/hooks/governor_config.json", ".claude/.governor-managed.json", ".claude/governor/governor.log",
                 ".claude/governor/state/s.json", "governance.yaml"]
GUARD_DIRS = [".claude/hooks/", ".claude/governor/state/"]
GUARD_BASENAMES = ["governance.yaml", ".governor-managed.json", "governor_config.json", "governor_*.py"]
GOVERNOR_ADMIN_SCRIPTS = {"exceptions.py", "governance.py"}   # human-only (X1); init/render cannot lower a tier
GOVERNOR_SCRIPTS = {"init.py", "render.py", "ask.py", "ci.py"}   # --human on these is human-only (I1d)
READ_ONLY = {"cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "rg", "ls", "dir", "wc", "diff", "stat",
             "file", "type", "jq", "bat", "get-content", "gc", "select-string", "sls", "test", "[", "realpath",
             "readlink", "sha256sum", "md5sum", "shasum", "get-filehash", "get-item", "gi", "get-childitem", "gci",
             "code", "vim", "view", "nano", "mkdir", "md"}
READ_ONLY_GIT = {"diff", "status", "log", "show", "blame", "add", "commit", "ls-files", "grep", "shortlog"}
CD = {"cd", "pushd", "set-location", "sl", "chdir", "popd"}


def _guard_path(tok, cwd):
    """Repo-relative, normalised form of a path-like token (quotes, ./, --opt=, backslashes removed)."""
    t = tok.strip("'\"")
    if "=" in t and t.startswith("-"):
        t = t.split("=", 1)[1]
    t = t.replace("\\", "/")
    low = t.lower()
    i = low.find("/.claude")
    if i >= 0 and not low.startswith(".claude"):
        t = t[i + 1:]
    elif cwd and not t.startswith(("/", "~", "-")):
        t = f"{cwd}/{t}"
    while t.startswith("./"):
        t = t[2:]
    return t


EMBEDDED_PATH = re.compile(r"[\w./~*?\\-]*\.claude[/\\][\w./*?\\-]*|[\w./\\-]*governance\.yaml|"
                           r"[\w./\\-]*governor_[\w*]*\.(py|json)|[\w./\\-]*\.governor-managed\.json", re.I)


def _guarded(tok, cwd):
    if re.search(r"[(),;'\"\s]", tok.strip("'\"")):   # code or a sentence: look for paths inside it
        return any(_guarded(m.group(0), "") for m in EMBEDDED_PATH.finditer(tok))
    t = _guard_path(tok, cwd)
    if not t or t.startswith("-"):
        return False
    low = t.lower().rstrip("/")
    if re.search(r"[*?\[]", low):
        # A glob counts only if it names Governor's files, or is a dot-glob that also matches `.claude`
        # (`rm -r .*`). Generic globs like `*.py` do not.
        first = low.split("/", 1)[0]
        if not (re.search(r"clau|governance|governor", low) or (first.startswith(".") and fnmatch.fnmatch(".claude", first))):
            return False
    base = low.rsplit("/", 1)[-1]
    if any(fnmatch.fnmatch(base, g) for g in GUARD_BASENAMES):
        return True
    if any((low + "/").startswith(d) for d in GUARD_DIRS):
        return True
    for target in GUARD_TARGETS:
        if low == target or fnmatch.fnmatch(target, low) or target.startswith(low + "/"):
            return True
    return False


def _is_read_only(toks):
    prog = _program(toks[0]).lower()
    if prog in READ_ONLY:
        return True
    if prog == "git":
        rest = [t for t in toks[1:] if not t.startswith("-")]
        return bool(rest) and rest[0] in READ_ONLY_GIT and not any(t.startswith("--output") for t in toks)
    if prog.startswith("python") and toks[1:3] == ["-m", "json.tool"]:
        return True
    if prog == "find":
        return not any(t in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls")
                       for t in toks)
    return False


def _abbrev_of(tok, flag):
    """True if tok is flag or any abbreviation argparse could expand to it (--h, --hu, ... ; also --flag=x)."""
    t = str(tok).lower().split("=", 1)[0]
    return len(t) >= 3 and t.startswith("--") and flag.startswith(t)


def guard_hit(cmd, tool="Bash"):
    """True if a shell command could modify Governor's guardrails or run its admin scripts (P9)."""
    for variant in expand_braces(strip_comments(cmd)):
        cwd = ""
        for seg in _split_compound(variant):
            if tool == "PowerShell":
                seg = seg.replace("\\", "/")
            try:
                toks = shlex.split(seg, posix=True)
            except ValueError:
                toks = seg.split()
            toks, _ = _strip_prefix(toks)
            if not toks:
                continue
            prog = _program(toks[0]).lower()
            if prog in CD:
                target = next((t for t in toks[1:] if not t.startswith("-")), "")
                new = _guard_path(target, cwd).rstrip("/") if target else ""
                cwd = new if ".claude" in new.lower() else ""
                continue
            if any(os.path.basename(t.replace("\\", "/")) in GOVERNOR_ADMIN_SCRIPTS for t in toks):
                return True
            if any(os.path.basename(t.replace("\\", "/")) == "remove.py" for t in toks) and \
                    any(t.lower() == "-y" or _abbrev_of(t, "--yes") for t in toks):
                return True   # U1: removing Governor is the user's action; the dry run stays allowed
            if any(_abbrev_of(t, "--human") for t in toks) and \
                    any(os.path.basename(t.replace("\\", "/")) in GOVERNOR_SCRIPTS for t in toks):
                return True
            # redirections write whatever the program
            for i, t in enumerate(toks):
                if t in (">", ">>", "1>", "2>") and i + 1 < len(toks) and _guarded(toks[i + 1], cwd):
                    return True
                if re.match(r"^\d?>{1,2}\S", t) and _guarded(t.lstrip("0123456789>"), cwd):
                    return True
            if _is_read_only(toks):
                continue
            args = [t for t in toks[1:] if t not in (">", ">>")]
            if prog in ("cp", "copy", "copy-item", "cpi", "rsync", "scp"):
                args = [t for t in args if not t.startswith("-")][-1:]   # only the destination is written
            if any(_guarded(t, cwd) for t in args):
                return True
            if cwd and any((cwd.lower() + "/").startswith(d) for d in GUARD_DIRS):
                return True   # any writing command run from inside .claude/hooks or Governor state
    return False
