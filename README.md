# Governor

Claude Code plugin that turns a repo plus a short intake into enforced agent governance:
permission rules, PreToolUse/PostToolUse/Stop hooks, a rules file, lint, drift checks, a CI gate
and a one-page evidence report. Rules: `SPEC.md`. Build order: `docs/BUILD_PLAN.md`.

## Install (private marketplace)

```
claude plugin marketplace add chittychat-studio/Governance-manager
claude plugin install governor@chittychat-governor
```
Needs Python 3.11+ with PyYAML (`python3 -m pip install pyyaml`). Hooks themselves are stdlib-only.

## Use

| Skill | What it does |
|---|---|
| `/governor:init [--with-ci]` | Detect facts, ask the missing ones, render and lint |
| `/governor:except --rule ID --reason "..."` | Disable one rule, or `--tier N` to lower the tier, with a recorded reason |
| `/governor:drift` | Fail if the repo's facts moved (new data class, exposure, tenancy, tier) |
| `/governor:doctor` | Read-only audit of an existing repo |
| `/governor:report` | One-page evidence report |

Packs exist for `fastapi-postgres` only. Other stacks are refused, not guessed.
Status is always one of generated / linted / verified. Only `scripts/verify.py`, run locally with
approval, can produce "verified", and only for the reference fixture.

## Develop

```
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
python scripts/sign_pack.py --check
```
