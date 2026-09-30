"""Release readiness (SPEC RL1, P4a): run every check a release needs and print the maintainer's remaining steps.
Makes no changes, no network calls (E2). Usage: python scripts/release_check.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import governance  # noqa: E402
import packs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def checks():
    out = []
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    v = plugin.get("version")
    out.append(("versions match (plugin.json, governance.py)", v == governance.GOVERNOR_VERSION,
                f"plugin {v}, governance {governance.GOVERNOR_VERSION}"))
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8") if (ROOT / "CHANGELOG.md").exists() else ""
    m = re.search(rf"^## {re.escape(str(v))} \((\d{{4}}-\d{{2}}-\d{{2}})\)", log, re.M)
    out.append((f"CHANGELOG has a dated '## {v} (YYYY-MM-DD)' entry", bool(m), "unreleased" if f"## {v}" in log else "missing"))
    r = subprocess.run([sys.executable, str(ROOT / "scripts/sign_pack.py"), "--check"], capture_output=True, text=True)
    out.append(("PACKS.lock matches the pack files", r.returncode == 0, r.stderr.strip()))
    try:
        status = packs.signature_status()
        out.append(("packs signed and verified (P4a)", status.startswith("signed (verified)"), status))
    except packs.PackError as exc:
        out.append(("packs signed and verified (P4a)", False, str(exc)))
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x"], cwd=ROOT, capture_output=True, text=True)
    out.append(("unit tests pass", r.returncode == 0, (r.stdout.strip().splitlines() or [""])[-1]))
    r = subprocess.run([sys.executable, str(ROOT / "scripts/eval.py"), "--out", str(ROOT / "evals/results")],
                       capture_output=True, text=True)
    out.append(("eval gates pass", r.returncode == 0, "see evals/results/latest.md"))
    tag = f"v{v}"
    r = subprocess.run(["git", "tag", "--list", tag], cwd=ROOT, capture_output=True, text=True)
    out.append((f"tag {tag} exists", tag in r.stdout.split(), "not tagged yet"))
    return out, v


def main():
    results, v = checks()
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'TODO'}  {name}" + ("" if ok else f"  ({detail})"))
    todo = [n for n, ok, _ in results if not ok]
    if todo:
        print("\nMaintainer steps left (docs/RELEASE.md):")
        if any("CHANGELOG" in n for n in todo):
            print(f"  - date the CHANGELOG entry: '## {v} (YYYY-MM-DD)'")
        if any("signed" in n for n in todo):
            print("  - python scripts/sign_pack.py --new-key <path outside the repo>   (first release only; back it up)")
            print("  - python scripts/sign_pack.py --sign-key <that path>; commit packs/SIGNING_KEY.pub, PACKS.lock.sig")
        if any("tag" in n for n in todo):
            print(f"  - after merging to main: git tag v{v} && git push origin v{v}")
        print("  - make the repository public (GitHub → Settings → General → Change visibility), then test the")
        print("    public install: /plugin marketplace add chittychat-studio/Governance-manager")
    return 0 if not todo else 1


if __name__ == "__main__":
    sys.exit(main())
