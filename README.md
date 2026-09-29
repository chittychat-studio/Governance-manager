# Governor

Claude Code plugin that turns a repo plus a short intake into enforced agent governance:
permission rules, PreToolUse/PostToolUse/Stop hooks, a rules file, lint, drift checks, a CI gate
and a one-page evidence report. Rules: `SPEC.md`. Build order: `docs/BUILD_PLAN.md`.

## Install (private marketplace)

The repo is private, so the simplest route is a local clone used as a directory marketplace:

```
git clone https://github.com/chittychat-studio/Governance-manager.git
claude plugin marketplace add ./Governance-manager
claude plugin install governor@chittychat-governor
```
Or straight from GitHub, if your git can already reach the private repo:
`claude plugin marketplace add chittychat-studio/Governance-manager` (append `@<branch>` for an unmerged branch).

Needs Python 3.11+ with PyYAML (`python -m pip install pyyaml`). Hooks themselves are stdlib-only.

## Test it on a local repo (Windows notes)

Packs exist for **FastAPI + Postgres** only (for example DeckForge); other stacks are refused.

1. `git switch -c governor-trial` in the target repo, so everything is one `git diff` to review or discard.
2. In Claude Code in that repo: `/governor:init`, answer the questions it asks.
3. `python -m pip show pyyaml` must work with the same `python` the hooks use: `governance.yaml` → `hook_python`
   (`python` on Windows, `python3` elsewhere). Lint warns if that command is not on PATH, because a hook that
   cannot start does **not** block anything.
4. Restart Claude Code in the repo (settings and hooks load at session start), then check the hooks fire
   using throwaway targets only, never real secrets or real folders, in case a hook fails open:
   create `governor-test-dir/` and a `.env.governor-test` holding a fake value, then ask Claude to run
   `rm -rf governor-test-dir` and to read `.env.governor-test`. Both must be refused citing a Governor rule,
   the folder must still exist, and `.claude/governor/governor.log` must show `deny P6-rm-rf` and
   `deny P6-secret-read`. Delete both test files afterwards yourself.
5. Undo: `git switch -` and delete the branch. Your original settings are also saved in
   `.claude/settings.json.governor-backup`.

Hooks run in exec form (no shell), so they behave the same whether Claude Code uses Git Bash or PowerShell.

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
