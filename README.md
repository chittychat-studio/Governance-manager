# Governor

A safety kit for AI coding agents in Claude Code. Install it in a project, answer up to 7 plain questions, and
Claude Code gets rules it cannot talk its way past. It cannot:
- wipe folders;
- read your secret keys;
- force-push over your history;
- switch its own safety off.

It must ask you before production deploys; projects with logins or personal data also get asks before database
changes and, at the strictest tier, package installs. It is told when it writes an API key into your code. It cannot
say "done" while your tests fail.

Every rule is labelled **enforced** (a hook or permission rule actually stops it) or **advisory** (only told to the
agent). Full rules: `SPEC.md`.

**What it is not:** a sandbox or a compliance certificate.

**What has been tested:**
- the eval corpora and deterministic trials on four real repos (`docs/TRIALS.md`);
- a hook check on a real Windows project.

A full live session has not been verified yet. Shell rules match the command text, so they stop the commands an
agent normally writes, not a determined attacker.

## Contents

- [What you get](#what-you-get)
- [Install](#install)
- [Set it up in a project](#set-it-up-in-a-project)
- [For vibe coders](#for-vibe-coders)
- [For developers](#for-developers)
- [Mandatory and optional features](#mandatory-and-optional-features)
- [Commands](#commands)
- [Project docs (optional)](#project-docs-optional)
- [What it costs you](#what-it-costs-you)
- [Uninstall](#uninstall)
- [How it works (technical)](#how-it-works-technical)
- [Evals](#evals)
- [Develop](#develop)

## What you get

Governor picks a **tier** from your answers. You are never asked which guardrails you want.

| Tier | When | Adds |
|---|---|---|
| 1 | No personal, payment or health data, and no public logins (an internal app with logins is tier 1) | 11 base rules (below) |
| 2 | Logins on a public app, or personal data used internally | + database dumps and destructive migrations ask first; no personal data in logs (advisory) |
| 3 | Personal data that is public or shared by many customers, or any payments or health data | + installing packages, web fetches and dumping the environment ask first; test data must be fake (advisory) |

**The base rules every project gets:**

| Blocked | Asks you first |
|---|---|
| Reading `.env`, private keys, cloud credentials | Production deploys (`vercel --prod`, `firebase deploy`, `terraform apply`…) |
| `rm -rf` and `Remove-Item -Recurse -Force` (except caches like `node_modules`) | Commands that call paid AI APIs |
| Force push | |
| Editing its own guardrails or running Governor's exception tools | |
| Encoded or downloaded scripts piped into a shell (`curl … \| sh`) | |
| MCP servers you have not allowed | |
| Saying "done" while your tests fail | |
| Repeating the same failing command more than 3 times | |

On top of that, every file the agent writes is scanned for API keys. This includes server secrets put in browser
variables, such as a Supabase service-role key in `NEXT_PUBLIC_…`.

JavaScript/TypeScript web apps (Next.js, React, Vite, Node, Supabase, Firebase) also get the Supabase Row Level
Security reminder. Python projects use the general rules; there are no Python-only rules yet.

**What a block looks like** (real output):

```
Blocked by Governor rule P6-secret-read: Do not read secret files (.env*, private keys, cloud credentials).
Why: Files like .env hold your passwords and API keys. An agent that reads them can leak them into logs, chats or commits.
What you can do: If the agent needs a setting, give it the variable name, not the value, or open the file yourself.
```

**What "asks you first" looks like:** Claude Code shows its normal approval prompt, with Governor's reason:

```
Governor rule P10-dependency-add: Adding or installing dependencies needs human approval.
Why: New packages run code on your machine and ship inside your app. A wrong or fake package is a common way in for attackers.
What you can do: Check the package name is the one you expect, then approve; say no if you are unsure.
```

## Install

You need Claude Code and Python 3.11 or newer, and nothing else: Governor uses only Python's standard library, with
no account and no API key. If you don't have Python, get it free from https://www.python.org/downloads/ (on
Windows, tick "Add python.exe to PATH").

**Once the repository is public:**
```
/plugin marketplace add chittychat-studio/Governance-manager
/plugin install governor@chittychat-governor
```

**While it is private:** clone it and add the clone as a local marketplace:
```
git clone https://github.com/chittychat-studio/Governance-manager.git
claude plugin marketplace add ./Governance-manager
claude plugin install governor@chittychat-governor
```

Installing the plugin changes nothing in your projects. A project is only governed after you run `/governor:init`
in it.

## Set it up in a project

1. Open the project in Claude Code. Ideally start on a new branch (`git switch -c governor-trial`), so everything is
   one `git diff`.
2. Run `/governor:init`. Governor looks at the project (stack, test command, logins, database, MCP servers), shows
   what it found and why, and asks only what it cannot see:

   ```
   What are you building?
   What information does it keep or handle? Pick all that apply.
     none: nothing about people · pii: names, emails, phone numbers, addresses · auth: user accounts,
     passwords or logins · payments · health · not sure
   Can anyone on the internet open it, or only you or your team?
   Will different customers or organisations share this one app, each seeing only their own data?
   How do you run your automated tests? Type the command, or 'none' if there are no tests yet.
   ```
   Every option has a one-line explanation. "Not sure" is fine: Governor picks the safer option and says so.
3. Read the result (tier, rules, warnings), then **commit** and **restart Claude Code** so the hooks load. Until you
   commit, `git stash` or `git reset --hard` would undo the install.
4. Check it works, using throwaway targets only:
   1. Create `governor-test-dir/` and `.env.governor-test` holding a fake value.
   2. Ask Claude to run `rm -rf governor-test-dir` and to read `.env.governor-test`.
   3. Both must be refused, and the folder must still exist.
   4. `/governor:status` must list them as blocked.
   5. On Windows, repeat with `Remove-Item -Recurse -Force governor-test-dir` and `Get-Content .env.governor-test`.

## For vibe coders

You don't need to know what a hook is.

- **Setup:** run `/governor:init` and answer the questions in your own words. "Not sure" always works.
- **No tests yet?** Answer `none` when asked for the test command. Governor then won't hold up "done" for tests.
  Don't let the agent write fake tests to get past it.
- **When something is blocked:** Claude tells you what, why and what you can do. If you really need it, you decide;
  the agent can't overrule a block on its own.
- **Optional project docs:** run `/governor:docs` for short starter docs (product, design, tasks, a memory file)
  that help Claude stay on track between sessions. See [Project docs](#project-docs-optional).
- **To see what you're protected from:** run `/governor:status`.

Example session:
```
You:     /governor:init
Claude:  Found: a Next.js app, tests run with `npm test`, Supabase login code.
         What data does it hold? ... Who can reach it? ...
You:     logins and user emails; anyone on the internet
Claude:  Tier 3 (strictest): 16 rules enforced, 3 advisory. Status: linted. Commit and restart Claude Code.
...
You:     add the left-pad package
Claude:  Governor asks before installing packages (P10-dependency-add). Approve?
```

## For developers

- **Source of truth:** `governance.yaml` holds detected facts, answers, tier, rule-pack hashes and exceptions.
  Review it like code, and commit everything Governor writes.
- **Your settings are merged, never overwritten:**
  - your entries in `.claude/settings.json` stay;
  - Governor's ownership is recorded in `.claude/.governor-managed.json`;
  - your text in `CLAUDE.md` / `AGENTS.md` outside Governor's marked block is kept byte for byte.
- **CI gate (optional):** `/governor:init --with-ci` adds `.github/workflows/governor.yml`. It runs lint and drift on
  every PR, so an edited hook or a project that outgrew its tier fails the build.
- **Exceptions are human-only and leave a record.** `/governor:except --rule P10-webfetch-ask --reason "docs site
  fetches are part of our build"` gives you the command to run in your own terminal. The reason, date and
  `git config user.email` go into `governance.yaml`, and the evidence report lists every exception.
- **Changes that weaken protection need you.** Re-running init cannot lower the tier: that needs an exception you
  record yourself (`/governor:except --tier N --reason "..."`). It cannot change the test command or allow new MCP
  servers unless you run it yourself in your own terminal with `--human`. The agent is blocked from passing that
  flag.
- **Codex:** with `agent: codex`, the same rules are written to a marked block in `AGENTS.md`. They are advisory
  only, because Governor installs no hooks for Codex.
- **Windows:** hooks cover Claude Code's PowerShell tool as well as Bash. A test command written with forward
  slashes, like `backend/.venv/Scripts/python.exe -m pytest`, is converted to backslashes when the test gate runs
  it (unit-tested; not yet run on a Windows machine).

## Mandatory and optional features

| Feature | Required? | How |
|---|---|---|
| Base rules, tier rules, secret scan, test gate | **Mandatory** once installed | `/governor:init` |
| Up to 7 questions about your project | **Mandatory**, once | `/governor:init` |
| Test gate | Mandatory, but can be off | Answer `none` for the test command if there are no tests yet |
| Project docs (PRD, architecture, rules, design, tasks, memory) | Optional | `/governor:docs` |
| CI gate on pull requests | Optional | `/governor:init --with-ci` |
| Allowing an MCP server | Optional, human-only | Init prints the `--mcp-allow NAME --human` command for your own terminal |
| Switching a rule off, or lowering the tier | Optional, human-only, needs a reason | `/governor:except` |
| Status, drift check, setup audit, evidence report | Optional, read-only | `/governor:status`, `/governor:drift`, `/governor:doctor`, `/governor:report` |
| Removing Governor | Optional, human-only | `/governor:remove` |

## Commands

| Command | What it does | Example |
|---|---|---|
| `/governor:init` | Detects facts, asks what it can't see, installs the rules, lints them | `/governor:init --with-ci` |
| `/governor:docs` | Optional project docs in `docs/project/` from 8 plain questions | `/governor:docs` |
| `/governor:status` | Plain-words view: tier and why, what is blocked, what needs your OK, recent blocks | `/governor:status` |
| `/governor:except` | Prepares a human-only exception with a written reason | `/governor:except --rule P10-webfetch-ask --reason "docs site fetches are part of our build"` |
| `/governor:drift` | Tells you when the project has changed enough to need stronger rules | `/governor:drift` |
| `/governor:doctor` | Read-only audit of an existing setup | `/governor:doctor` |
| `/governor:report` | One-page evidence report (not a certificate) | `/governor:report` |
| `/governor:remove` | Shows what would be removed; you confirm in your own terminal | `/governor:remove` |

## Project docs (optional)

`/governor:docs` asks 8 plain questions:
1. What you're building.
2. The problem it solves.
3. Who it's for.
4. 1–8 features.
5. Look and feel.
6. Brand colours.
7. Current milestone.
8. Any coding rules you already follow (optional).

It then creates six files in `docs/project/`:

| File | Contains | Loaded |
|---|---|---|
| `rules.md` | dev rules, general principles, coding standards, project structure | every session (max 40 lines) |
| `memory.md` | current status, completed, in progress, next | every session (max 40 lines) |
| `design.md` | design principles, colour palette, typography, UI components | a one-line pointer to it loads when Claude works on UI files |
| `PRD.md` | overview, problem, goals, target users, core features | only when a task needs it |
| `architecture.md` | app flow, architecture, tech stack, folder structure | only when a task needs it |
| `task.md` | setup, authentication (if you have logins), one section per feature | only when a task needs it |

- **Filled from your answers, not written by AI.** If you answer "not sure" about the product, problem, users,
  features or milestone, you get a visible `TODO`, never made-up text. For look, colours and coding rules you get
  neutral defaults, labelled as defaults to replace.
- **The files are yours.** Governor creates each file once and never overwrites it, and removing Governor keeps
  them.
- **Advisory only:** Claude is asked to keep `memory.md` current, by replacing it at the end of each task; nothing
  enforces that.
- **Guarded, because they load every session:** `rules.md` and `memory.md` stay within 40 lines and 4,000
  characters, may not contain `@` lines (Claude Code would import another file, such as `.env`, through them) or
  text telling Claude to switch guardrails off. Claude's edits to them are checked as they happen, shell commands may
  not write to them, and lint checks them again in CI. A repo that ships its own unsafe `rules.md` is refused, and
  Governor never writes through a symbolic link.

For example, answering "a notes app for students" with features "add a note, tag notes, share a note" gives a
`task.md` with sections Project setup, Authentication, Add a note, Tag notes and Share a note.

## What it costs you

Governor makes no model or API calls of its own. What it adds to your Claude session, measured on sample projects
(token figures are estimates at about 4 characters per token):

| When | About |
|---|---|
| Every session: rules file + skill list | ~1,000 tokens |
| Every session, if you use `/governor:docs`: index + `rules.md` + `memory.md` | ~450 tokens more |
| Each time something is blocked or needs your OK | ~110 tokens |
| Each allowed command | 0 tokens, ~40 ms |
| When Claude tries to finish after changing files | your test suite runs; skipped if nothing changed since it last passed |

If your full test suite is slow, use a faster subset as the test command.

## Uninstall

Run `/governor:remove`. It shows exactly what would be removed and what is kept, and changes nothing. To remove,
run the printed command yourself in a terminal outside Claude Code (the agent is blocked from doing it):

```
python3 <plugin-dir>/scripts/remove.py . --yes           # remove Governor, keep governance.yaml
python3 <plugin-dir>/scripts/remove.py . --yes --purge   # also delete governance.yaml (tier, exceptions)
```

- **Removed:**
  - Governor's entries in `.claude/settings.json`;
  - its hooks, rules file and state;
  - its block in `CLAUDE.md` / `AGENTS.md`;
  - the CI files it wrote.
- **Kept:**
  - everything that is yours, including your settings, your text and `docs/project/`;
  - a settings file that only Governor changed is restored to your exact original bytes.

Afterwards, restart Claude Code and review `git diff`. To remove the plugin itself from Claude Code, use the
`/plugin` menu.

## How it works (technical)

- **Source of truth:** `governance.yaml` holds:
  - detected facts and answers;
  - the tier (a lookup in `tiers.yaml`, no LLM);
  - rule packs (`packs/tier{1,2,3}/{generic,node,fastapi-postgres}/`), hash-pinned in `PACKS.lock` and
    Ed25519-signed once a maintainer key exists (`packs/SIGNING_KEY.pub`);
  - exceptions.
- **What render writes:**
  - `.claude/settings.json` (merged);
  - hooks in `.claude/hooks/`;
  - `.claude/rules/governor.md`;
  - a coverage table;
  - a marked block in `CLAUDE.md` / `AGENTS.md`.
- **Hooks:** they run in exec form (no shell) and cover Claude Code's Bash, PowerShell and Monitor tools.
- **Status words:** always one of generated / linted / verified. Only `scripts/verify.py`, run locally with
  approval, can produce "verified", and only for the reference fixture.

## Evals

`python scripts/eval.py` scores the deterministic layer against labelled corpora in `evals/`:
- attack and everyday commands, fired at the real rendered hooks for Bash and PowerShell;
- repo layouts, run through detect and init;
- secret-scan lines;
- multi-step pipeline scenarios.

It fails if any gate in `evals/thresholds.yaml` fails. The latest scorecard is `evals/results/latest.md`, and CI
runs it on every PR.

`evals/edge.yaml` covers:
- novice users;
- prompt injection planted in repo files;
- forged answer files;
- hostile test commands;
- attempts to switch guardrails off.

Live-agent behaviour is measured only by `scripts/live_edge.py`, which spends credits or plan usage (E4), so run
it on your own machine:

```
python scripts/live_edge.py --plan                      # estimate only (8 scenarios x 2 runs, ~960k tokens)
python scripts/live_edge.py --only LE4 --runs 1 --keep  # one scenario first
python scripts/live_edge.py                             # the full suite; asks you to type yes
```

No live results exist yet.

## Develop

```
pip install -r requirements.txt -r requirements-dev.txt   # development only; users need nothing
python -m pytest
python scripts/eval.py
python scripts/sign_pack.py --check
```
