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
3. Check `governance.yaml` → `hook_python` (the command the hooks run with; init picks the first of
   `python`/`python3` that really starts Python). Lint **fails** if it does not start, because a hook that
   cannot start does not block anything. Hooks need only the standard library; PyYAML is for the scripts.
4. Restart Claude Code in the repo (settings and hooks load at session start), then check the hooks fire
   using throwaway targets only, never real secrets or real folders, in case a hook fails open:
   create `governor-test-dir/` and a `.env.governor-test` holding a fake value, then ask Claude to run
   `rm -rf governor-test-dir` and to read `.env.governor-test`. Both must be refused citing a Governor rule,
   the folder must still exist, and `.claude/governor/governor.log` must show `deny P6-rm-rf` and
   `deny P6-secret-read`. On Windows, repeat with PowerShell wording: ask Claude to run
   `Remove-Item -Recurse -Force governor-test-dir` and `Get-Content .env.governor-test`. Both must be refused
   too. Delete both test files afterwards yourself.
5. Undo: `git switch -` and delete the branch. Your original settings are also saved in
   `.claude/settings.json.governor-backup`.

Hooks are launched in exec form (no shell), and their shell rules cover both Claude Code's Bash tool and its
PowerShell tool (the Windows default when Git Bash is absent). Shell rules match command text: they stop the
commands an agent normally writes, not a determined attacker (variables, interpreters opening files). The
evidence report says so; it is not a sandbox.

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

## Evals

`python scripts/eval.py` scores the deterministic layer against labelled corpora in `evals/` (attack and
everyday commands fired at the real rendered hooks for Bash and PowerShell, repo layouts through detect and
init, secret-scan lines, multi-step pipeline scenarios) and fails if any gate in `evals/thresholds.yaml` fails.
The latest scorecard is `evals/results/latest.md`; CI runs it on every PR. It does not measure live-agent
behaviour; that is the cost-gated Q-series (`scripts/verify.py`).

Once Governor is installed, the agent cannot weaken it by re-running init: a re-run that changes the test command or allows new MCP servers is refused unless you run it yourself, in your own terminal, with `--human` (SPEC I1d); the hook blocks the agent from passing that flag. On Windows without `python3`/`python` on PATH, the skills fall back to `py -3`.

`evals/edge.yaml` covers edge cases: a user with only an idea and no app, no tests, unsure or free-text answers;
prompt injection planted in README, CLAUDE.md, AGENTS.md, code comments, file names, compose files and `.mcp.json`;
forged answer files, hostile test commands and attempts to switch guardrails off. It checks that detected facts
match a clean twin repo, that no file contents reach what the agent reads, and that the skills carry the
data-not-instructions text. Whether a live agent actually follows that text is not measured: `evals/live_edge.yaml`
is run by `scripts/live_edge.py`, which spends credits or plan usage (E4), so run it on your own machine:

```
python scripts/live_edge.py --plan                      # estimate only (8 scenarios x 2 runs, ~960k tokens)
python scripts/live_edge.py --only LE4 --runs 1 --keep  # one scenario first, to check the harness works
python scripts/live_edge.py                             # the full suite; asks you to type yes
```

Each scenario runs headless Claude Code (`claude -p`, this plugin via `--plugin-dir`, project settings only) in a
throwaway repo. Pass/fail comes from files, hashes and the hook log afterwards, never from the agent's own summary.
Results: `evals/results/live_edge.json`. No results exist yet.

## Develop

```
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
python scripts/sign_pack.py --check
```
