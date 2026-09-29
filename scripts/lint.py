"""Lint rendered Governor output (SPEC V1-V7, R3, R4, R6).

Usage: python scripts/lint.py <repo>   -> exit 0 clean, 1 on any failure (V7)
"""
import ast
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import governance  # noqa: E402
import render  # noqa: E402
from packs import PackError  # noqa: E402

LINE_CAP = 150
# V4: extended only by editing SPEC V4.
FORBIDDEN = ["as needed", "where appropriate", "best practices", "ensure security"]


def _unscoped_rules(repo):
    for p in sorted((repo / ".claude" / "rules").rglob("*.md")) if (repo / ".claude" / "rules").exists() else []:
        text = p.read_text(encoding="utf-8")
        if not re.match(r"^---\s*\n(.*\n)*?paths\s*:", text):
            yield p, text


def lint(repo):
    """Return (failures, warnings) lists of 'Vn: message' strings (V1-V7)."""
    repo = Path(repo).resolve()
    fails, warns = [], []
    gov = governance.read(repo)
    if gov is None:
        return ["V1: governance.yaml missing"], warns
    try:
        render.verify_pins(gov)
    except render.RenderError as exc:
        fails.append(f"V2: {exc}")
        return fails, warns
    managed_p = repo / render.MANAGED
    if not managed_p.exists():
        return fails + ["V1: rendered files missing (run render.py)"], warns
    managed = json.loads(managed_p.read_text(encoding="utf-8"))
    if not (repo / render.COVERAGE_MD).exists():
        fails.append("V1: coverage table missing (R6)")
    if "codex" in gov["packs"]:
        _lint_codex(repo, gov, fails)
    if "claude-code" in gov["packs"]:
        _lint_claude(repo, gov, managed, fails, warns)
    return fails, warns


def _lint_codex(repo, gov, fails):
    """V1-V4 for the AGENTS.md block (E7)."""
    p = repo / render.AGENTS_MD
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    if render.BLOCK_START not in text or render.BLOCK_END not in text:
        fails.append("V1: AGENTS.md Governor block missing")
        return
    block = text.split(render.BLOCK_START, 1)[1].split(render.BLOCK_END, 1)[0]
    for sec in render.SECTIONS:
        if sec not in block:
            fails.append(f"V1: AGENTS.md block missing section '{sec}'")
    rules, disabled = render.split_rules(gov, "codex")
    for r in rules:
        want = f"- {r['id']}: disabled: " if r["id"] in disabled else f"- {r['id']}: "
        if want not in block:
            fails.append(f"V2: AGENTS.md missing {r['id']}")
    if len(block.splitlines()) > LINE_CAP:
        fails.append(f"V3: AGENTS.md Governor block is {len(block.splitlines())} lines > {LINE_CAP}")
    for phrase in FORBIDDEN:
        if phrase in block.lower():
            fails.append(f"V4: '{phrase}' in AGENTS.md block")


def _lint_claude(repo, gov, managed, fails, warns):
    """V1-V6 for Claude Code outputs."""
    rules_p = repo / render.RULES_MD
    if not rules_p.exists():
        fails.append(f"V1: {render.RULES_MD} missing (run render.py)")
        return
    rules_md = rules_p.read_text(encoding="utf-8")

    # V1 required sections
    for s in render.SECTIONS:
        if s not in rules_md:
            fails.append(f"V1: {render.RULES_MD} missing section '{s}'")

    # V2 every selected rule id present, enabled or disabled-with-reason
    try:
        rules, disabled = render.split_rules(gov, "claude-code")
    except PackError as exc:
        fails.append(f"V2: {exc}")
        return
    for r in rules:
        if r["id"] in disabled:
            if f"- {r['id']}: disabled: " not in rules_md:
                fails.append(f"V2: {r['id']} disabled without rendered reason (X2)")
        elif f"- {r['id']}: " not in rules_md:
            fails.append(f"V2: rule {r['id']} missing from output")

    # V3 line cap on CLAUDE.md + unscoped rules (R3)
    owned = sum(len(t.splitlines()) for p, t in _unscoped_rules(repo) if t.startswith(render.MD_HEADER))
    claude_md = repo / "CLAUDE.md"
    cm_lines = len(claude_md.read_text(encoding="utf-8").splitlines()) if claude_md.exists() else 0
    user_rules = sum(len(t.splitlines()) for p, t in _unscoped_rules(repo) if not t.startswith(render.MD_HEADER))
    if managed.get("claude_md_owned"):
        owned += cm_lines
        user = user_rules
    else:
        user = cm_lines + user_rules
    if owned > LINE_CAP:
        fails.append(f"V3: Governor-generated always-loaded text is {owned} lines > {LINE_CAP}")
    elif owned + user > LINE_CAP:
        warns.append(f"V3: CLAUDE.md + unscoped rules total {owned + user} lines > {LINE_CAP} "
                     f"({user} are yours; Governor does not rewrite your files)")

    # V4 forbidden phrases in generated markdown
    for rel in [render.RULES_MD, render.COVERAGE_MD] + (["CLAUDE.md"] if managed.get("claude_md_owned") else []):
        text = (repo / rel).read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN:
            if phrase in text:
                fails.append(f"V4: '{phrase}' in {rel}")

    # V5 pack denies/asks (minus disabled) present in settings.json; extras reported
    settings_p = repo / ".claude" / "settings.json"
    try:
        settings = json.loads(settings_p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fails.append(f"V6: settings.json unreadable: {exc}")
        return
    perms = settings.get("permissions", {})
    for key in ("deny", "ask"):
        want = [x for r in rules if r["id"] not in disabled for x in r.get(key, [])]
        have = perms.get(key, [])
        for x in want:
            if x not in have:
                fails.append(f"V5: settings.json {key} missing '{x}'")
        extra = [x for x in have if x not in want]
        if extra:
            warns.append(f"V5: {key} entries not from the pack (kept, R5): {extra}")

    # V6 hooks parse, are executable, JSON valid, hooks registered
    for name in render.HOOK_FILES:
        p = repo / ".claude" / "hooks" / name
        if not p.exists():
            fails.append(f"V6: hook {name} missing")
            continue
        try:
            ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            fails.append(f"V6: {name} does not parse: {exc}")
        if os.name == "posix" and not os.access(p, os.X_OK):
            fails.append(f"V6: {name} not executable")
    try:
        json.loads((repo / ".claude" / "hooks" / "governor_config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fails.append(f"V6: governor_config.json invalid: {exc}")
    hooks = settings.get("hooks", {})
    pythons = set()
    for event in render.HOOK_EVENTS:
        ours = [h for g in hooks.get(event, []) if isinstance(g, dict) for h in g.get("hooks", [])
                if render.is_governor_hook(h)]
        if not ours:
            fails.append(f"V6: {event} hook not registered in settings.json")
        pythons |= {h.get("command", "") for h in ours if h.get("args")}
    for py in sorted(pythons):
        if shutil.which(py) is None:
            warns.append(f"V6: hook interpreter '{py}' is not on PATH here; hooks would error and NOT block. "
                         "Set hook_python in governance.yaml and re-render.")
    for event, groups in hooks.items():
        if not isinstance(groups, list) or not all(isinstance(g, dict) and isinstance(g.get("hooks"), list)
                                                   for g in groups):
            fails.append(f"V6: settings.json hooks.{event} has invalid shape")

    # R4 headers on wholly generated files
    for rel in managed.get("files", []):
        p = repo / rel
        if p.suffix in (".md", ".py") and p.exists():
            head = p.read_text(encoding="utf-8")[:200]
            if "Generated by Governor" not in head:
                fails.append(f"R4: {rel} missing generated header")


def main(argv=None):
    """CLI: V7 non-zero exit on any failure."""
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    fails, warns = lint(argv[0])
    for w in warns:
        print("warning:", w)
    for f in fails:
        print("FAIL:", f)
    print("status: linted" if not fails else f"lint failed: {len(fails)} problem(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
