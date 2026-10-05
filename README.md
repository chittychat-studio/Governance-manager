# Governor

A safety kit for AI coding agents. Install it in a project, answer up to 7 plain questions, and Claude Code gets
rules it cannot talk its way past: it cannot wipe folders, read your secret keys, force-push over your history or
switch its own safety off; it must ask you before deploying, installing packages or changing your database; it
gets told when it writes an API key into your code; and it cannot say "done" while your tests fail.
Every rule is labelled **enforced** (actually blocked) or **advisory** (only told to the agent). Rules: `SPEC.md`.

Installs on any project: every project gets the general rules above, and JavaScript/TypeScript web apps (Next.js,
React, Vite, Node, Supabase, Firebase) get a few extra ones. Python projects (FastAPI, Django, Flask) use the general
rules; there are no Python-only rules yet. It is not a sandbox or a compliance certificate. Tested so far on the eval
corpora and in deterministic trials on four real repos (docs/TRIALS.md); not yet verified in a live Claude Code
session.

## What you need

Claude Code and Python 3.11 or newer. Nothing else: Governor uses only Python's standard library.
No Python? Get it free from https://www.python.org/downloads/ (on Windows, tick "Add python.exe to PATH").

## Install

Once the repository is public:
```
/plugin marketplace add chittychat-studio/Governance-manager
/plugin install governor@chittychat-governor
```
While it is private, clone it and add the clone as a local marketplace:
```
git clone https://github.com/chittychat-studio/Governance-manager.git
claude plugin marketplace add ./Governance-manager
claude plugin install governor@chittychat-governor
```

## Use

| Command | What it does |
|---|---|
| `/governor:init` | Looks at your project, asks what it can't see (in plain words; "not sure" is fine), installs the rules |
| `/governor:docs` | Optional. A few plain questions, then lean project docs in `docs/project/`: PRD, architecture, rules, design, tasks, memory. Only `rules.md` and `memory.md` load every session (40 lines each at most); the rest are read when needed |
| `/governor:status` | In plain words: what you are protected from, what needs your OK, what was blocked recently |
| `/governor:except --rule ID --reason "..."` | Switch one rule off with a written reason (you run it, not the agent) |
| `/governor:remove` | Shows what Governor would remove; you confirm it yourself with `--yes` |
| `/governor:drift` | Tells you when the project has changed enough to need stronger rules |
| `/governor:doctor` | Read-only check of an existing setup |
| `/governor:report` | One-page evidence report |

When something is blocked, the message says what, why, and what you can do instead. Answering "not sure" picks the
safer option and records that it was assumed. Commit straight after installing: until you do, `git stash` or
`git reset --hard` would undo the install.

## Test it on your own repo first

1. `git switch -c governor-trial`, so everything is one `git diff` to review or throw away.
2. In Claude Code: `/governor:init`, answer the questions, then restart Claude Code.
3. Check it fires, using throwaway targets only: make `governor-test-dir/` and `.env.governor-test` with a fake
   value, ask Claude to run `rm -rf governor-test-dir` and to read `.env.governor-test`. Both must be refused, the
   folder must still exist, and `/governor:status` must show them under "blocked". On Windows repeat with
   `Remove-Item -Recurse -Force governor-test-dir` and `Get-Content .env.governor-test`.
4. Use it for real work for a few days, then follow `docs/TRIALS.md` to record what it blocked that you wanted.
5. To undo: `/governor:remove`, or `git switch -` and delete the branch.

## How it works (technical)

`governance.yaml` is the single source: detected facts, answers, tier (lookup in `tiers.yaml`), rule packs
(`packs/tier{1,2,3}/{generic,node,fastapi-postgres}/`, hash-pinned in `PACKS.lock`, Ed25519-signed once a
maintainer key exists: `packs/SIGNING_KEY.pub`) and exceptions. Render writes `.claude/settings.json` (merged, never
overwritten; ownership in `.claude/.governor-managed.json`), hooks in `.claude/hooks/`, `.claude/rules/governor.md`,
a coverage table and a marked block in CLAUDE.md / AGENTS.md. Hooks run in exec form (no shell) and cover Claude
Code's Bash, PowerShell and Monitor tools. Shell rules match command text: they stop the commands an agent normally
writes, not a determined attacker (variables, interpreters opening files); the report says so.
Status is always one of generated / linted / verified. Only `scripts/verify.py`, run locally with approval, can
produce "verified", and only for the reference fixture.

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
