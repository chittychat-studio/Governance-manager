"""Deterministic eval suite: scores Governor against labelled corpora and release gates.

Suites (evals/*.yaml):
  enforcement  commands and tool calls fired at the real rendered hooks, as Claude Code would
  detection    repo layouts -> detected facts, tier or refusal via init (host claude-code)
  secrets      lines the PostToolUse secret scan must / must not flag
  pipeline     multi-step flows: init, exceptions, tamper, lint, drift, doctor, report, CI gate
Gates: evals/thresholds.yaml. No network, no model calls (E2): this measures the deterministic layer only;
live-agent behaviour is the Q-series (scripts/verify.py, cost-gated).

Usage: python scripts/eval.py [--out evals/results]
Exit 0 when every gate passes, 1 otherwise.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import detect  # noqa: E402
import doctor  # noqa: E402
import drift  # noqa: E402
import exceptions  # noqa: E402
import governance  # noqa: E402
import init  # noqa: E402
import lint  # noqa: E402
import render  # noqa: E402
import report  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
TIER_INTAKE = {
    1: {"data_classes": ["none"], "exposure": "internal", "tenancy": "single"},
    2: {"data_classes": ["auth"], "exposure": "public", "tenancy": "single"},
    3: {"data_classes": ["auth", "pii"], "exposure": "public", "tenancy": "single"},
}
BASE_INTAKE = {"app_type": "api", "stack": "fastapi-postgres", "agent": ["claude-code"], "test_cmd": "python -m pytest"}
NO_VERIFY = Path("/nonexistent/governor-eval-verify.json")


def _load(name):
    return yaml.safe_load((EVALS / f"{name}.yaml").read_text(encoding="utf-8"))


def _materialise(root, files):
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in (files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
    return root


# ---------------------------------------------------------------- enforcement
def _install_tier(work, tier):
    repo = work / f"tier{tier}"
    repo.mkdir(parents=True)
    governance.write(repo, governance.build(dict(BASE_INTAKE, **TIER_INTAKE[tier])))
    render.render(repo)
    got = governance.read(repo)["tier"]["effective"]
    if got != tier:
        raise RuntimeError(f"eval setup: wanted tier {tier}, got {got}")
    return repo


def _event(case, repo):
    tool = case["tool"]
    if tool in ("Bash", "PowerShell"):
        ti = {"command": case["cmd"]}
    elif tool in ("Read", "Write", "Edit"):
        p = case["path"]
        ti = {"file_path": p if p.startswith(("~", "/")) else str(repo / p)}
    elif tool == "Grep":
        ti = {"pattern": "x", "glob": case["glob"]}
    elif tool == "Glob":
        ti = {"pattern": case["glob"]}
    else:
        ti = {}
    return {"session_id": f"eval-{case['id']}", "cwd": str(repo), "hook_event_name": "PreToolUse",
            "tool_name": tool, "tool_input": ti}


def _fire(repo, event):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(repo))
    r = subprocess.run([sys.executable, str(repo / ".claude/hooks/governor_pretool.py")], input=json.dumps(event),
                       capture_output=True, text=True, env=env, timeout=60)
    rule = None
    if r.returncode == 2:
        decision = "deny"
        if "Governor rule " in r.stderr:
            rule = r.stderr.split("Governor rule ", 1)[1].split(":", 1)[0].strip()
    elif r.returncode == 0 and r.stdout.strip():
        out = json.loads(r.stdout)["hookSpecificOutput"]
        decision = out["permissionDecision"]
        reason = out.get("permissionDecisionReason", "")
        rule = reason.split("Governor rule ", 1)[1].split(":", 1)[0].strip() if "Governor rule " in reason else None
    elif r.returncode == 0:
        decision = "allow"
    else:
        decision = f"FAIL-OPEN(exit {r.returncode})"
    return decision, rule


def run_enforcement(work):
    cases = _load("enforcement")["cases"]
    repos = {t: _install_tier(work, t) for t in (1, 2, 3)}
    rows = []
    for c in cases:
        repo = repos[c.get("tier", 3)]
        decision, rule = _fire(repo, _event(c, repo))
        rows.append({**{k: c.get(k) for k in ("id", "kind", "tool", "expect", "rule", "tier")},
                     "input": c.get("cmd") or c.get("path") or c.get("glob") or c["tool"],
                     "decision": decision, "got_rule": rule, "ok": decision == c["expect"]})
    by = lambda k: [r for r in rows if r["kind"] == k]  # noqa: E731
    attacks, benign, friction, gaps = by("attack"), by("benign"), by("friction"), by("gap")
    stopped = [r for r in attacks if r["decision"] in ("deny", "ask")]
    attributed = [r for r in stopped if r["rule"] and r["got_rule"] == r["rule"]]
    with_rule = [r for r in stopped if r["rule"]]
    fp = [r for r in benign if r["decision"] != "allow"]
    metrics = {
        "cases": len(rows),
        "fail_open": sum(r["decision"].startswith("FAIL-OPEN") for r in rows),
        "attack_stopped": _rate(len(stopped), len(attacks)),
        "attack_exact": _rate(sum(r["ok"] for r in attacks), len(attacks)),
        "rule_attribution": _rate(len(attributed), len(with_rule)),
        "benign_false_positive": _rate(len(fp), len(benign)),
        "friction_exact": _rate(sum(r["ok"] for r in friction), len(friction)),
        "gaps_stopped": f"{sum(r['decision'] in ('deny', 'ask') for r in gaps)}/{len(gaps)}",
    }
    failures = [r for r in rows if r["kind"] != "gap" and not r["ok"]] + \
               [r for r in stopped if r["rule"] and r["got_rule"] != r["rule"]]
    by_rule = {}
    for r in attacks:
        k = r["rule"] or "?"
        s = by_rule.setdefault(k, [0, 0])
        s[0] += r["decision"] in ("deny", "ask")
        s[1] += 1
    return {"metrics": metrics, "by_rule": {k: f"{a}/{b}" for k, (a, b) in sorted(by_rule.items())},
            "failures": failures, "gaps": gaps}


# ---------------------------------------------------------------- detection
def run_detection(work):
    rows = []
    for c in _load("detection")["cases"]:
        repo = _materialise(work / "det" / c["id"], c["files"])
        problems = []
        det = detect.detect(repo)["detected"]
        if c["id"].startswith("D11"):
            det = init._detect(repo, "claude-code")["detected"]
        for k, v in (c.get("expect") or {}).items():
            if det.get(k) != v:
                problems.append(f"{k}: want {v!r}, got {det.get(k)!r}")
        dc = set(det.get("data_classes", []))
        for x in c.get("data_classes_include", []):
            if x not in dc:
                problems.append(f"data_classes missing {x!r} (got {sorted(dc)})")
        for x in c.get("data_classes_exclude", []):
            if x in dc:
                problems.append(f"data_classes wrongly include {x!r}")
        code, lines = init.install(repo, c.get("answers") or {}, host="claude-code")
        if "refused" in c:
            if code == 0 or c["refused"] not in " ".join(lines):
                problems.append(f"want refusal containing {c['refused']!r}, got code {code}: {lines[:1]}")
        else:
            gov = governance.read(repo)
            got = gov["tier"]["effective"] if gov else None
            if code != 0 or got != c["tier"]:
                problems.append(f"want tier {c['tier']} (code 0), got tier {got} code {code}: {lines[:1]}")
        rows.append({"id": c["id"], "ok": not problems, "problems": problems})
    return {"metrics": {"cases": len(rows), "detection_accuracy": _rate(sum(r["ok"] for r in rows), len(rows))},
            "failures": [r for r in rows if not r["ok"]]}


# ---------------------------------------------------------------- secrets
def run_secrets(_work):
    spec = importlib.util.spec_from_file_location("gov_post", ROOT / "templates/hooks/governor_posttool.py")
    sys.path.insert(0, str(ROOT / "templates/hooks"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = [{"id": c["id"], "want": c["hit"], "got": bool(mod.scan_text(c["line"])), "line": c["line"]}
            for c in _load("secrets")["cases"]]
    pos = [r for r in rows if r["want"]]
    neg = [r for r in rows if not r["want"]]
    return {"metrics": {"cases": len(rows), "secret_recall": _rate(sum(r["got"] for r in pos), len(pos)),
                        "secret_false_positive": _rate(sum(r["got"] for r in neg), len(neg))},
            "failures": [r for r in rows if r["want"] != r["got"]]}


# ---------------------------------------------------------------- pipeline
def _tree_hash(repo):
    h = hashlib.sha256()
    for p in sorted(repo.rglob("*")):
        rel = p.relative_to(repo).as_posix()
        if rel.startswith(".claude/governor") or "__pycache__" in rel:
            continue
        h.update(rel.encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def _step(repo, s, state):
    do, want = s["do"], s.get("expect")
    if do == "init":
        code, lines = init.install(repo, s.get("answers") or {}, with_ci=s.get("with_ci", False), host="claude-code")
        text = " ".join(lines)
        if want == "ok":
            gov = governance.read(repo)
            tier_ok = "tier" not in s or (gov and gov["tier"]["effective"] == s["tier"])
            return code == 0 and tier_ok, f"code {code}; {lines[:2]}"
        return code != 0 and s.get("contains", "") in text, f"code {code}; {lines[:1]}"
    if do == "lint":
        fails, _ = lint.lint(repo)
        ok = not fails if want == "pass" else any(f.startswith(s.get("code", "")) for f in fails) and fails
        return bool(ok), str(fails[:3])
    if do == "drift":
        f = drift.check(repo)["failures"]
        ok = not f if want == "pass" else bool(f) and any(s.get("contains", "") in x for x in f)
        return ok, str(f[:3])
    if do == "doctor":
        rep = doctor.audit(repo)
        missing = rep.get("missing", ["<error>"])
        ok = not missing if want == "pass" else set(s.get("missing_include", [])) <= set(missing)
        return ok, str(missing[:6])
    if do == "report":
        text = report.build(repo, verify_path=NO_VERIFY)
        return s["text"] in text, "text not found" if s["text"] not in text else ""
    if do in ("write", "append"):
        p = repo / s["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text((p.read_text() if do == "append" and p.exists() else "") + s["text"], encoding="utf-8")
        return True, ""
    if do == "except":
        try:
            exceptions.add(repo, rule=s.get("rule"), tier=s.get("tier"), reason=s["reason"], user="eval@governor.local")
            return want == "ok", "accepted"
        except exceptions.ExceptionRefused as exc:
            return want == "refused", str(exc)
    if do == "render":
        try:
            render.render(repo)
            return want == "ok", "rendered"
        except (render.RenderError, ValueError) as exc:
            return want == "refused", str(exc)
    if do == "settings_has":
        data = json.loads((repo / ".claude/settings.json").read_text(encoding="utf-8"))
        perms = data.get("permissions", {})
        missing = [k for k in s.get("keys", []) if k not in data]
        missing += [x for x in s.get("allow", []) if x not in perms.get("allow", [])]
        missing += [x for x in s.get("deny", []) if x not in perms.get("deny", [])]
        return not missing, f"missing {missing}"
    if do == "absent":
        return not (repo / s["path"]).exists(), f"{s['path']} exists"
    if do == "snapshot":
        state["snap"] = _tree_hash(repo)
        return True, ""
    if do == "unchanged_since_snapshot":
        return _tree_hash(repo) == state.get("snap"), "tree changed"
    if do == "vendored":
        r = subprocess.run([sys.executable, f".governor/scripts/{s['script']}", "."], cwd=repo, capture_output=True,
                           text=True, timeout=120)
        return (r.returncode == 0) == (want == "pass"), (r.stdout + r.stderr)[-300:]
    raise ValueError(f"unknown step {do}")


def run_pipeline(work):
    data = _load("pipeline")
    rows = []
    for sc in data["scenarios"]:
        repo = _materialise(work / "pipe" / sc["id"], data["bases"][sc["base"]])
        state, failed = {}, None
        for i, s in enumerate(sc["steps"], 1):
            try:
                ok, detail = _step(repo, s, state)
            except Exception as exc:  # noqa: BLE001 - a crash is a scenario failure, reported not raised
                ok, detail = False, f"crashed: {type(exc).__name__}: {exc}"
            if not ok:
                failed = {"step": i, "do": s["do"], "detail": detail}
                break
        rows.append({"id": sc["id"], "ok": failed is None, "failed": failed})
    return {"metrics": {"cases": len(rows), "pipeline_pass": _rate(sum(r["ok"] for r in rows), len(rows))},
            "failures": [r for r in rows if not r["ok"]]}


# ---------------------------------------------------------------- scoring
def _rate(n, d):
    return round(n / d, 4) if d else 1.0


def gates(metrics, th):
    checks = [
        ("fail_open", metrics["enforcement"]["fail_open"] <= th["fail_open_max"], f"<= {th['fail_open_max']}"),
        ("attack_stopped", metrics["enforcement"]["attack_stopped"] >= th["attack_stopped_min"], f">= {th['attack_stopped_min']}"),
        ("attack_exact", metrics["enforcement"]["attack_exact"] >= th["attack_exact_min"], f">= {th['attack_exact_min']}"),
        ("rule_attribution", metrics["enforcement"]["rule_attribution"] >= th["rule_attribution_min"], f">= {th['rule_attribution_min']}"),
        ("benign_false_positive", metrics["enforcement"]["benign_false_positive"] <= th["benign_false_positive_max"], f"<= {th['benign_false_positive_max']}"),
        ("friction_exact", metrics["enforcement"]["friction_exact"] >= th["friction_exact_min"], f">= {th['friction_exact_min']}"),
        ("detection_accuracy", metrics["detection"]["detection_accuracy"] >= th["detection_accuracy_min"], f">= {th['detection_accuracy_min']}"),
        ("secret_recall", metrics["secrets"]["secret_recall"] >= th["secret_recall_min"], f">= {th['secret_recall_min']}"),
        ("secret_false_positive", metrics["secrets"]["secret_false_positive"] <= th["secret_false_positive_max"], f"<= {th['secret_false_positive_max']}"),
        ("pipeline_pass", metrics["pipeline"]["pipeline_pass"] >= th["pipeline_pass_min"], f">= {th['pipeline_pass_min']}"),
    ]
    return [{"gate": g, "pass": ok, "target": t} for g, ok, t in checks]


def scorecard(res, gate_rows):
    m = {k: v["metrics"] for k, v in res.items() if isinstance(v, dict) and "metrics" in v}
    lines = ["# Governor eval scorecard", "",
             f"{res['meta']['date']} · Governor {res['meta']['governor_version']} · commit {res['meta']['commit']}",
             "", "Deterministic layer only (hooks, detect, pipeline). Live-agent behaviour is the Q-series "
             "(`scripts/verify.py`), not measured here.", "", "## Gates", "", "| Gate | Value | Target | Result |",
             "|---|---|---|---|"]
    flat = {**m["enforcement"], **m["detection"], **m["secrets"], **m["pipeline"]}
    for g in gate_rows:
        lines.append(f"| {g['gate']} | {flat[g['gate']]} | {g['target']} | {'PASS' if g['pass'] else '**FAIL**'} |")
    e = res["enforcement"]
    lines += ["", "## Enforcement", "", f"{m['enforcement']['cases']} cases fired at the rendered hooks "
              f"(tiers 1-3, Bash and PowerShell tools). Documented gaps stopped anyway: {m['enforcement']['gaps_stopped']}.",
              "", "| Rule | Attacks stopped |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in e["by_rule"].items()]
    sections = [("Enforcement misses", e["failures"],
                 lambda r: f"- {r['id']} ({r['kind']}, {r['tool']}): `{r['input']}` → {r['decision']}"
                           f"{' via ' + str(r['got_rule']) if r['got_rule'] else ''}; expected {r['expect']}"
                           f"{' via ' + r['rule'] if r.get('rule') else ''}"),
                ("Documented gaps (P7 limits, not gated)", e["gaps"],
                 lambda r: f"- {r['id']}: `{r['input']}` → {r['decision']}"),
                ("Detection misses", res["detection"]["failures"], lambda r: f"- {r['id']}: {'; '.join(r['problems'])}"),
                ("Secret-scan misses", res["secrets"]["failures"],
                 lambda r: f"- {r['id']}: {'missed' if r['want'] else 'false positive'}: `{r['line']}`"),
                ("Pipeline failures", res["pipeline"]["failures"],
                 lambda r: f"- {r['id']}: step {r['failed']['step']} ({r['failed']['do']}): {r['failed']['detail']}")]
    for title, items, fmt in sections:
        lines += ["", f"## {title}", ""] + ([fmt(r) for r in items] or ["- none"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(EVALS / "results"))
    args = ap.parse_args(argv)
    work = Path(tempfile.mkdtemp(prefix="governor-eval-"))
    try:
        res = {"enforcement": run_enforcement(work), "detection": run_detection(work),
               "secrets": run_secrets(work), "pipeline": run_pipeline(work)}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    res["meta"] = {"date": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                   "governor_version": governance.GOVERNOR_VERSION, "commit": commit or "unknown"}
    th = yaml.safe_load((EVALS / "thresholds.yaml").read_text(encoding="utf-8"))
    gate_rows = gates({k: v["metrics"] for k, v in res.items() if k != "meta"}, th)
    res["gates"] = gate_rows
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.json").write_text(json.dumps(res, indent=2, default=str) + "\n", encoding="utf-8")
    card = scorecard(res, gate_rows)
    (out / "latest.md").write_text(card, encoding="utf-8")
    print(card)
    return 0 if all(g["pass"] for g in gate_rows) else 1


if __name__ == "__main__":
    sys.exit(main())
