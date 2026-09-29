"""Lint rendered Governor output (SPEC V1-V9, R3, R4, R6).

Usage: python scripts/lint.py <repo>   -> exit 0 clean, 1 on any failure (V7)
"""
import ast
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import governance  # noqa: E402
import render  # noqa: E402
from packs import PackError  # noqa: E402
from pyfind import works  # noqa: E402

LINE_CAP = 150
# V4: extended only by editing SPEC V4.
FORBIDDEN = ["as needed", "where appropriate", "best practices", "ensure security"]
# V10: text telling the agent to switch guardrails off. Extended only by editing SPEC V10.
GUARDRAIL_OFF = [
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) instructions",
    r"disable(s|d)? (all |the |its |governor'?s? )*hooks",
    r"disableAllHooks",
    r"bypassPermissions",
    r"dangerously-skip-permissions",
    r"ignore (the )?governor",
    r"governor (is|has been) (deprecated|disabled|turned off|off)",
    r"(turn|switch) off (the )?(governor|guardrails|hooks)",
    r"(do not|don't) (follow|obey) (the )?(governor|hooks|guardrails)",
]
INSTRUCTION_FILES = ["CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md", "AGENTS.md"]


def _unscoped_rules(repo):
    for p in sorted((repo / ".claude" / "rules").rglob("*.md")) if (repo / ".claude" / "rules").exists() else []:
        text = p.read_text(encoding="utf-8")
        if not re.match(r"^---\s*\n(.*\n)*?paths\s*:", text):
            yield p, text


def lint(repo):
    """Return (failures, warnings) lists of 'Vn: message' strings (V1-V10)."""
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
    _lint_consistency(gov, fails)
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
    _lint_integrity(repo, managed, fails)
    warns += guardrail_off_text(repo)
    return fails, warns


def guardrail_off_text(repo):
    """V10: warnings for instruction files whose text outside Governor's blocks tells the agent to switch
    guardrails off. Advisory: the user's own text is never changed, only pointed at."""
    repo = Path(repo)
    files = [repo / f for f in INSTRUCTION_FILES]
    files += sorted((repo / ".claude" / "rules").rglob("*.md")) if (repo / ".claude" / "rules").is_dir() else []
    files += sorted((repo / ".claude" / "skills").rglob("SKILL.md")) if (repo / ".claude" / "skills").is_dir() else []
    out = []
    for f in files:
        if not f.is_file() or f.as_posix().endswith(render.RULES_MD):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        while render.BLOCK_START in text and render.BLOCK_END in text.split(render.BLOCK_START, 1)[1]:
            head, rest = text.split(render.BLOCK_START, 1)
            text = head + rest.split(render.BLOCK_END, 1)[1]
        for n, line in enumerate(text.splitlines(), 1):
            hit = next((pat for pat in GUARDRAIL_OFF if re.search(pat, line, re.I)), None)
            if hit:
                out.append(f"V10: {f.relative_to(repo).as_posix()}:{n} tells the agent to switch guardrails off; "
                           "this text loads every session. Remove it unless you wrote it on purpose.")
                break
    return out


def _lint_consistency(gov, fails):
    """V9: governance.yaml agrees with itself: tier recomputed from intake, exceptions well-formed (X1, X4),
    effective tier and pack ids follow from them (T6, P1). Catches a hand-lowered tier or a fake exception."""
    import datetime
    from intake import IntakeError, validate
    from packs import resolve
    from select_pack import pack_id
    from tier import compute_tier
    try:
        validate(dict(gov["intake"]))
        computed, _ = compute_tier(gov["intake"])
    except (IntakeError, KeyError, TypeError) as exc:
        fails.append(f"V9: intake invalid: {exc}")
        return
    try:
        from render import test_cmd_problem
        problem = test_cmd_problem(gov)
    except (PackError, KeyError, TypeError, ValueError) as exc:
        problem = f"cannot check test_cmd: {exc}"
    if problem:
        fails.append(f"V9: {problem}")
    if gov["tier"].get("computed") != computed:
        fails.append(f"V9: tier.computed is {gov['tier'].get('computed')} but intake gives {computed}")
    valid_tiers = []
    known = set()
    for agent in gov.get("packs", {}):
        try:
            known |= {r["id"] for r in resolve(pack_id(computed, gov["intake"]["stack"], agent))[0]}
        except PackError:
            pass
    for i, e in enumerate(gov.get("exceptions", [])):
        problems = []
        if len(str(e.get("reason", "")).strip()) < 20:
            problems.append("reason under 20 characters (X1)")
        try:
            datetime.date.fromisoformat(str(e.get("date")))
        except ValueError:
            problems.append("no valid date (X1)")
        if not str(e.get("by", "")).strip():
            problems.append("no recorded user (X1)")
        if e.get("kind") == "tier":
            if not isinstance(e.get("tier"), int) or not 1 <= e["tier"] <= 3:
                problems.append("tier exception needs a tier between 1 and 3 (X4)")
            elif not problems:
                valid_tiers.append(e["tier"])
        elif e.get("kind") == "rule":
            if e.get("rule") not in known:
                problems.append(f"rule {e.get('rule')} is not in the selected packs")
        else:
            problems.append("unknown kind")
        if problems:
            fails.append(f"V9: exception #{i + 1}: {'; '.join(problems)}")
    effective = min([computed] + valid_tiers)
    if gov["tier"].get("effective") != effective:
        fails.append(f"V9: tier.effective is {gov['tier'].get('effective')} but intake + valid exceptions give "
                     f"{effective}")
    agents = set(gov["intake"].get("agent", []))
    if set(gov.get("packs", {})) != agents:
        fails.append(f"V9: packs are for {sorted(gov.get('packs', {}))} but intake agents are {sorted(agents)}")
    for agent, p in gov.get("packs", {}).items():
        want = pack_id(effective, gov["intake"]["stack"], agent)
        if p.get("pack_id") != want:
            fails.append(f"V9: {agent} pack is {p.get('pack_id')} but tier {effective} needs {want}")


def _norm(text):
    return text.replace("\r\n", "\n")


def _governor_hooks(repo):
    """{event: sorted [(matcher, handler JSON)]} for Governor's own hook handlers in settings.json."""
    try:
        data = json.loads((repo / ".claude/settings.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    hooks = data.get("hooks") if isinstance(data, dict) and isinstance(data.get("hooks"), dict) else {}
    for event, groups in hooks.items():
        for g in groups if isinstance(groups, list) else []:
            for h in g.get("hooks", []) if isinstance(g, dict) else []:
                if isinstance(h, dict) and render.is_governor_hook(h):
                    out.setdefault(event, []).append((g.get("matcher"), json.dumps(h, sort_keys=True)))
    return {k: sorted(v, key=str) for k, v in out.items()}


def _agents_block(text):
    if render.BLOCK_START in text and render.BLOCK_END in text:
        return text.split(render.BLOCK_START, 1)[1].split(render.BLOCK_END, 1)[0]
    return None


def _lint_integrity(repo, managed, fails):
    """V8: every Governor-generated file equals a fresh render of governance.yaml. Catches hooks or
    config edited by hand or by the agent (for example a pretool hook replaced with sys.exit(0))."""
    tmp = Path(tempfile.mkdtemp(prefix="governor-lint-"))
    try:
        for rel in ("governance.yaml", "CLAUDE.md", "AGENTS.md", ".claude/settings.json", render.MANAGED):
            if (repo / rel).exists():
                (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(repo / rel, tmp / rel)
        try:
            render.render(tmp)
        except (render.RenderError, PackError) as exc:
            fails.append(f"V8: cannot re-render for comparison: {exc}")
            return
        expected = json.loads((tmp / render.MANAGED).read_text(encoding="utf-8")).get("files", [])
        for rel in sorted(set(expected) | set(managed.get("files", []))):
            want, have = tmp / rel, repo / rel
            if not have.exists():
                fails.append(f"V8: {rel} missing; re-run render")
            elif not want.exists() or _norm(want.read_text(encoding="utf-8")) != _norm(have.read_text(encoding="utf-8")):
                fails.append(f"V8: {rel} differs from a fresh render (edited or stale); re-run render")
        if (tmp / ".claude/settings.json").exists():
            want_h, have_h = _governor_hooks(tmp), _governor_hooks(repo)
            for event in sorted(set(want_h) | set(have_h)):
                if want_h.get(event) != have_h.get(event):
                    fails.append(f"V8: settings.json {event} Governor hook entry differs from a fresh render "
                                 f"(matcher, command, args or timeout changed)")
        for name in (render.AGENTS_MD, "CLAUDE.md"):
            want_p, have_p = tmp / name, repo / name
            want = _agents_block(want_p.read_text(encoding="utf-8")) if want_p.exists() else None
            if want is None:
                continue
            have = _agents_block(have_p.read_text(encoding="utf-8", errors="replace")) if have_p.exists() else None
            if _norm(want) != _norm(have or ""):
                fails.append(f"V8: {name} Governor block differs from a fresh render")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
        block = _agents_block(claude_md.read_text(encoding="utf-8", errors="replace")) or ""
        owned += len(block.splitlines())
        user = user_rules + max(0, cm_lines - len(block.splitlines()))
    else:
        user = cm_lines + user_rules
    if owned > LINE_CAP:
        fails.append(f"V3: Governor-generated always-loaded text is {owned} lines > {LINE_CAP}")
    elif owned + user > LINE_CAP:
        warns.append(f"V3: CLAUDE.md + unscoped rules total {owned + user} lines > {LINE_CAP} "
                     f"({user} are yours; Governor does not rewrite your files)")

    # V4 forbidden phrases in generated markdown
    for rel in [render.RULES_MD, render.COVERAGE_MD] + (["CLAUDE.md"] if managed.get("claude_md_owned") else []):
        text = (repo / rel).read_text(encoding="utf-8", errors="replace").lower()
        text = (_agents_block(text) or "") if rel == "CLAUDE.md" else text
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
    # V6: settings that switch hooks or permissions off entirely
    for name in ("settings.json", "settings.local.json"):
        p = repo / ".claude" / name
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
        except (OSError, json.JSONDecodeError):
            data = {}
        data = data if isinstance(data, dict) else {}
        if data.get("disableAllHooks") is True:
            fails.append(f"V6: .claude/{name} sets disableAllHooks: every Governor hook is off")
        if data.get("allowManagedHooksOnly") is True:
            fails.append(f"V6: .claude/{name} sets allowManagedHooksOnly: project hooks will not run")
        mode = (data.get("permissions") or {}).get("defaultMode") if isinstance(data.get("permissions"), dict) else None
        if mode == "bypassPermissions":
            warns.append(f"V6: .claude/{name} sets defaultMode bypassPermissions: ask rules will not prompt")
    hooks = settings.get("hooks", {}) if isinstance(settings.get("hooks"), dict) else {}
    pythons = set()
    for event in render.HOOK_EVENTS:
        ours = [h for g in hooks.get(event, []) if isinstance(g, dict) for h in g.get("hooks", [])
                if render.is_governor_hook(h)]
        if not ours:
            fails.append(f"V6: {event} hook not registered in settings.json")
        pythons |= {h.get("command", "") for h in ours if h.get("args")}
    for py in sorted(pythons):
        if not works(py):
            fails.append(f"V6: hook interpreter '{py}' does not start Python 3.8+ here; hooks would error and "
                         "NOT block. Set hook_python in governance.yaml and re-render.")
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
