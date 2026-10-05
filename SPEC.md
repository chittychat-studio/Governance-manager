# Governor — Specification v0.3

Status: draft v0.3 (Phase 0 review), 2026-09-29. Every line of code must trace to a rule ID below.
Confidence tags: [C] certain, [L] likely, [G] guessing — [G] rules must be verified before implementation.

---

## E — Execution model

- **E1** Governor runs inside Claude Code as a plugin (commands + skills + hooks). No standalone app, no hosted backend, no web UI in v1.
- **E2** Deterministic steps (detect, tier, select, render, lint, drift, doctor) are Python scripts in the plugin's `scripts/`. They make zero network calls.
- **E3** LLM steps (compose, red-team) run as subagents inside the *user's own* Claude Code session, billed to the user's own Claude plan or credits. Governor code never holds an API key and never calls a model API directly.
- **E4** Maintainer credits are spent only on: development sessions, Q-series verify runs, the live edge suite (`scripts/live_edge.py`, scenarios in `evals/live_edge.yaml`, measuring L5 behaviour of a real agent; added 2026-09-29 with Sandhya's approval), and the C1 nightly compatibility job. Interactive runs print an estimated cost and wait for approval before executing. Unattended runs (C1) cannot wait: they run only under a pre-approved monthly cap recorded in the repo, and refuse to start once the cap is reached.
- **E4a** Cost estimate = number of scripted tasks × per-task token budget (a constant in the script) × the price in `docs/pricing.yaml`, which records its source URL and check date. An estimate from a price older than 90 days is printed with a warning.
- **E5** (Applies only once compose exists — see NX4.) Compose output is cached on `sha256(governance.yaml + pack versions + template version)`. Cache hit = no subagent call.
- **E6** All generated config is project-scoped and committed: `.claude/settings.json`, `.claude/hooks/`, `.claude/rules/`, `CLAUDE.md`. Never write to `~/.claude/`. Reason: Claude Code cloud sessions do not read the user's local `~/.claude/settings.json`, so only project-scoped config travels to both local and cloud sessions. [L — re-verify each release]
- **E7** Codex target in v1 = `AGENTS.md` only, as a marked block that leaves the user's own text intact. Every rule is advisory for Codex and the coverage table says so. No Codex config file until Codex's project-level config is confirmed [G]. No Codex-hosted inference path.
- **E8** Everything a user runs (init, render, lint, drift, doctor, report, status, remove, exceptions, hooks) needs only Python 3.11+ and its standard library. YAML is read and written by Governor's own subset reader (`scripts/miniyaml.py`), checked against PyYAML on every YAML file in the repo. PyYAML stays a development dependency (tests, evals, verify). When Python is missing or too old, the message says in plain words how to install it.

## I — Intake

- **I1** Required fields: `app_type`, `stack`, `data_classes[]`, `exposure`, `tenancy`, `agent`, `test_cmd`. Optional: `integrations[]`, `regulation[]`, `conventions{pkg_mgr, branch_rule, banned_libs[]}`.
- **I1a** Closed enums, defined in `intake.schema.json`: `data_classes` ⊆ {`none`, `pii`, `auth`, `payments`, `health`}; `exposure` ∈ {`public`, `internal`}; `tenancy` ∈ {`single`, `multi`}; `agent` ⊆ {`claude-code`, `codex`}. `auth` = the app stores user credentials or session tokens. A value outside the enum → refuse (I2), never map to tier 1.
- **I1b** `test_cmd` is run by the Stop hook outside PreToolUse, so it gets the same checks as an agent command: init refuses, and lint V9 fails, a `test_cmd` that contains a line break or that the rendered PreToolUse rules would deny or ask for (for example `curl … | sh`, `rm -rf`, running `exceptions.py`), or that cannot fail (`true`, `:`, `exit 0`, `echo …` alone, or ending in `|| true` / `; true` / `|| exit 0`).
- **I1d** Once `governance.yaml` exists, a re-run of init that changes `test_cmd` or adds servers to `mcp_allow` is refused unless it carries `--human`. The PreToolUse guard denies any Governor script command containing `--human`, so only the user can pass it, from their own terminal (P9, X1).
- **I1c** `test_cmd: none` records that the repo has no test suite yet. The Stop-hook test gate is then inactive, and the rules file, coverage table and evidence report say so. Correcting a detected test command to `none` is refused (I3a), because it switches the gate off.
- **I1e** `not sure` is an accepted answer to `exposure`, `tenancy`, `data_classes` and `app_type`. It records the higher-risk value (`public`, `multi`, `pii` added, `fullstack`), lists the field under `assumed` in `governance.yaml`, and the report says which answers were assumed. It never lowers a tier (I1a still refuses any other unknown value).
- **I1f** The Stop hook runs `test_cmd` from the repo root through the platform shell. On Windows, `/` in the program path (the first word) is turned into `\` before it runs, because cmd.exe reads `backend/.venv/...` as a command called `backend`; `governance.yaml` keeps the text as written, so the same value works on every OS. If the program cannot start (exit 127 or 126, or 9009 on Windows), the block message says the test command could not start and how to fix it, not that tests are failing; the loop guard still applies. init's not-found warning resolves a relative program path against the repo, the same way.
- **I2** Any required field empty after detect + ask → refuse, naming the field. No partial output.
- **I3** `detect.py` runs before any question is asked; only `unknown[]` fields are asked.
- **I3a** Detected facts are shown with their evidence and the user may correct them (not counted as questions under I4). A correction may keep or raise risk; one that lowers it (drop a data class, public→internal, multi→single, or a stack correction that moves to a pack family with fewer rules) is refused and needs an X4 exception. Corrections are recorded in `governance.yaml`. When Governor runs as a Claude Code plugin, `claude-code` is always among the agents.
- **I4** Maximum 7 questions per run. Required `unknown[]` fields are asked first; optional fields only with the remaining budget.
- **I5** Questions ask about facts or conventions only. Never ask the user which controls, guardrails or security measures they want.
- **I5a** Questions come only from a fixed bank in `ask.py`; each entry maps to exactly one I1 field. No free-form questions.
- **I5b** Questions are written for someone who has never heard of the terms: every option carries a one-line plain explanation, and the stack question offers everyday choices (a JavaScript/TypeScript web app, a Python app, other / not sure) instead of asking for a framework-database string.

## T — Tiering

- **T0** Rules T2–T5 are checked in order; the highest matching tier wins.
- **T1** Tier is derived by lookup from `tiers.yaml` (versioned). No LLM involvement.
- **T2** `payments` or `health` in `data_classes` → tier 3.
- **T3** `pii` with `exposure=public` or `tenancy=multi` → tier 3. [G — validate table on 3 real repos]
- **T4** `pii` internal single-tenant, or `auth` with public exposure → tier 2. [G]
- **T5** Everything else → tier 1.
- **T6** A tier can only be lowered through an X-series exception (X4). Re-running init with answers that lower the computed tier is refused unless such an exception exists.

## P — Rule packs

- **P1** Packs are hand-written YAML keyed by `(tier, family, agent)`. Selection is pure lookup.
- **P1a** Every repo gets a pack. The stack maps to a pack family by lookup: an exact pack for the stack if one exists; else `node` for JavaScript/TypeScript stacks (next, react, vite, node, express, nuxt, svelte, remix, astro, nest, and any stack whose first part is one of these); else `generic`. The `generic` family holds every stack-neutral rule (all of P6–P10); stack families extend it and only add. A stack with no family of its own is never refused for that reason.
- **P2** Every rule carries: `id`, `text`, `enforcement: enforced | advisory`, `mechanism: deny_rule | hook | sandbox | ci | instruction`, `agents: [claude-code, codex]`.
- **P3** Tier N pack is a strict superset of tier N−1.
- **P4** v1: each pack's sha256 is pinned in `governance.yaml`; hash mismatch → refuse to install.
- **P4a** `packs/PACKS.lock` is signed with Ed25519 (RFC 8032), implemented in Python's standard library so verification works offline on every platform (E2, E8). The public key is committed as `packs/SIGNING_KEY.pub`; the private key is a 32-byte seed file the maintainer keeps outside the repository and never commits. `scripts/sign_pack.py --sign-key PATH` writes `packs/PACKS.lock.sig`. When `SIGNING_KEY.pub` exists, a missing or invalid signature → refuse to install (fail closed). Docs, coverage table and evidence report say "signed" only when the signature verified; otherwise "hash-pinned, not signed". Limit: whoever can replace the pack files can also delete the public key, which drops back to "hash-pinned"; so status prints the key's fingerprint and each release's notes publish it, for the user to compare. The implementation is tested against the RFC 8032 test vectors.
- **P5** Hook scripts use Python stdlib only. No third-party dependencies.
- **P6** Base pack (all tiers) must include:
  - deny reads of `.env*`, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, and cloud credential paths: `~/.aws/`, `~/.config/gcloud/`, `~/.azure/`, `~/.kube/config`, `~/.docker/config.json`
  - MCP servers allow-listed by name; anything unlisted denied
  - recursive force delete and force push → deny; prod deploy/apply commands (one list in the generic pack, P11) → ask
  - PostToolUse secret scan on Edit/Write; each run appends one line to `.claude/governor/governor.log` (no file content)
  - Stop hook that runs `test_cmd` and blocks "done" if red, with a loop guard so it cannot block indefinitely: Governor releases after 3 consecutive blocks, and Claude Code itself overrides after 8 (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`) [L — seen in the Claude Code 2.1.284 binary, not in the docs page]
- **P7a** Encoded or downloaded commands piped into a shell (`base64 -d | sh`, `curl … | sh`, `powershell -EncodedCommand`, `| iex`) → deny, all tiers.
- **P7b** Shell comments are removed before rules match only when the command is plain enough that the removal is certain: no backslash, no `$'…'` quoting, no backtick, no heredoc (`<<`) and balanced quotes. Anything else is matched with the comment left in (fail closed: a comment may cause an ask or deny, never an allow). Found in review of v0.2.0: `echo a\ #; rm -rf src` hid the rm from every rule.
- **P6a** Exempt from the recursive-force-delete rule: regenerable directories given as plain relative paths (`__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.venv`, `venv`, `node_modules`, `dist`, `build`, `htmlcov`, `.next`, `coverage`, `.tox`, `.nox`). Onboarding steps that name `.env` without reading it are exempt from the secret-read rule (`cp .env.example .env`, Windows `copy` / `Copy-Item` of the same, `touch .env`, `--env-file .env`).
- **P7** Every P6 deny item is layered: permission deny rule **and** PreToolUse hook. Shell rules cover both the `Bash` and `PowerShell` tools (Windows uses PowerShell by default when Git Bash is absent). A hook decision never depends on logging succeeding; malformed input or an incomplete hook config blocks. Reason: Bash rules match command text only (`/bin/rm`, `bash -c '…'`, `git -C . push` are not matched), and a hook exiting 2 blocks before permission rules are evaluated. Neither is an OS boundary; the evidence report must not claim one. [C — code.claude.com/docs/en/permissions, "What a Bash rule doesn't match"]
- **P8** Cost pack: same failing command 3 times in a session → block (N is a pack field, default 3); commands matching the pack's `paid_cli` list → ask.
- **P9** Guardrail self-edit applies at **every tier** (moved to the base pack after the 2026-09-29 review); the rest of P9 is tier 2+. The agent cannot edit its own guardrails, including by `cd` into `.claude/`, globs, or code that opens the files, and cannot run Governor's exception tools (`exceptions.py`, `governance.py`) or pass `--human` (or any abbreviation of it) to a Governor script (I1d), or run `remove.py` with `--yes` or any abbreviation (U1); every Governor command line refuses abbreviated options (`allow_abbrev=False`) — a human runs those (X1). The `Monitor` tool runs shell commands, so it gets the same PreToolUse checks as `Bash`. Tier-2 additions (added in Phase 2, pending Sandhya's review): the agent cannot edit its own guardrails (`.claude/settings.json`, `.claude/settings.local.json`, `.claude/hooks/`, `governance.yaml`, Governor state) through edit tools or shell commands → deny; database dump commands → ask; destructive migrations (`DROP`, `TRUNCATE`, `alembic downgrade`, `dropdb`, migrate reset) → ask; advisory: no personal data in logs or fixtures.
- **P10** Tier-3 additions (added in Phase 2, pending Sandhya's review): dependency installs → ask; WebFetch → ask; environment dumps (`env`, `printenv`) → ask; advisory: fixtures use provider test tokens and synthetic records only.
- **P10a** The dependency rule asks when a command adds a package named on the command line. Restoring what the project already declares is exempt only in its plain forms: `npm install` / `npm ci` / `pnpm install` / `yarn install` / `bun install` with no package, and only listed flags (no `--prefix`, `-C`, `--cwd`, `--registry`, `--global`); `pip install -r` of a `requirements*.txt` / `*.in` path inside the repo (no absolute path, no `..`, no URL) and `pip install -e` of `.` or a path inside the repo; `poetry` / `pdm` / `pipenv` `install` and `uv sync` with listed flags only; never after `cd` / `pushd` in the same command. The exemption also needs every manifest and lock file to be byte-identical to the session's baseline, which the hook records at the first tool call of the session (in Governor state, which the agent cannot write, P9), so an edit made during the session, committed or not, makes restores ask. The hook does not run git for this. Found in real-repo trials: 5 of 6 asks were restores of declared dependencies; review of v0.2.0 found the git-based check could be bypassed.
- **P10b** The `Monitor` tool's WebSocket input (`ws`) is outbound network access: it asks wherever WebFetch asks (tier 3).
- **P11** Additions aimed at JavaScript/TypeScript web apps (Supabase, Firebase). In the shared secret-scan hook, so every family gets it: the secret scan flags server secrets put in client-exposed variables (`NEXT_PUBLIC_`, `VITE_`, `EXPO_PUBLIC_`, `REACT_APP_` names containing SECRET, SERVICE_ROLE, SERVICE_KEY, PRIVATE, PASSWORD or ending in `_SK`); every match on a line is checked, so a placeholder earlier on the line cannot hide a real value later; advisory: keep Row Level Security on for every Supabase table and never use the service-role key in client code. Deploy (`vercel --prod`, `netlify deploy --prod`, `firebase deploy`, `supabase db push`, `wrangler deploy`, `railway up`), destructive migration (`prisma migrate reset`, `supabase db reset`, `drizzle-kit drop`) and install (`bun add`, `npm i <pkg>`) commands are in the generic rules, so every family gets them.
- **P12** Every enforced rule carries `plain` (why, in words a non-developer understands) and `you_can` (what the user can do instead). Deny and ask messages show both after the rule text. Pack validation refuses an enforced rule without them.
- **P2a** A rule's `mechanism` may list several mechanisms (P7 layering = `[deny_rule, hook]`). `deny_rule` covers permission rules in either the deny or the ask list.

## R — Rendering

- **R1** `governance.yaml` is the single source (intake + tier + pack refs + hashes + exceptions).
- **R2** Claude Code outputs: `CLAUDE.md`, `.claude/settings.json`, `.claude/rules/*.md`, `.claude/hooks/*.py`, `.claude/.governor-managed.json`. Codex outputs: `AGENTS.md`, Codex config (E7).
- **R3** `CLAUDE.md` plus every `.claude/rules/*.md` without `paths:` frontmatter ≤ 150 lines combined (both load every session). Content is only pack rule text, the commands block, exceptions and the fixed R7 working agreement; no other free prose.
- **R4** Every file Governor wholly generates starts with a header: generated by Governor, edit `governance.yaml` instead. JSON files cannot carry comments; for `.claude/settings.json` (merged per R5) ownership is recorded in `.claude/.governor-managed.json` instead.
- **R5** Existing `settings.json` is merged, never overwritten. Back up first; record Governor-owned keys in `.claude/.governor-managed.json`. Governor owns only entries it added: an entry the user already had, even if identical to a pack entry, is never removed. Settings are validated before any file is written.
- **R6** Output includes a coverage table per agent: rules enforced vs advisory.
- **R7** The rules file (and the AGENTS.md block) ends with a fixed `## Working agreement` section, the same for every repo and labelled advisory (nothing enforces it): (a) keep replies short and on the user's stated goal; read and run only what the task needs, to save the user's token budget; (b) ask one short question before guessing when the request is unclear, or before any step that a rule above blocks or asks about; never look for another route to a blocked action; (c) before saying done, check the work against the rules above and the Commands line and say which were checked; (d) one line of thanks. At most 6 lines; its text lives in `render.py` only, never from repo text (L1). Positive wording in (d) is a maintainer choice, not a claimed effect.

## PD — Project docs (optional, `/governor:docs`)

- **PD1** `/governor:docs` is optional and separate from init, so init keeps its short question bank (I5). It needs an installed Governor (`governance.yaml`). It writes six files to `docs/project/`: `PRD.md` (product overview, problem statement, goals, target users, core features), `architecture.md` (app flow, high-level architecture, technology stack, folder structure), `rules.md` (dev rules, general principles, technology and coding standards, project structure), `design.md` (design principles, colour palette, typography, UI components), `task.md` (project setup, then one section per feature; authentication only when `auth` is in `data_classes`), `memory.md` (current status, completed, in progress, next, notes).
- **PD2** Questions come from a fixed bank in `scripts/docs.py` (I5a): product, problem, users, features (1–8), look (closed choice), colours (hex values or "not sure"), milestone, conventions (optional). Free-text answers are single-line and capped at 300 characters (features at 80 each); line breaks and leading `#` are removed. "not sure" or a blank answer leaves a visible `TODO:` in the file, never invented text (evidence only). Stack, app type, data classes and test command come from `governance.yaml`, not new questions.
- **PD3** Template only: files are filled deterministically from the answers and `governance.yaml`. No model writes their content (NX4, E2). The folder list in `architecture.md` comes from the repo's top two directory levels, skipping dependency and build folders, names quoted and capped at 30 entries (L1a).
- **PD4** Create once, then the files are the user's. An existing file is never overwritten; docs.py reports it as kept. Re-running fills only missing files. `/governor:remove` keeps them.
- **PD5** Token budget. Only `rules.md` and `memory.md` load every session (imported from Governor's CLAUDE.md block), each capped at 40 lines. `design.md` loads only when Claude works on UI files, through a scoped `.claude/rules/governor-design.md` with `paths:` frontmatter. `PRD.md`, `architecture.md` and `task.md` are listed in a short index in the block and read only when a task needs them. Codex gets the same index as plain text (no imports).
- **PD6** Lint V11 fails when `docs/project/rules.md` or `docs/project/memory.md` is over 40 lines, and V3 counts both toward the always-loaded cap (R3). A recorded doc that is missing is a V11 warning, not a failure (the user may delete their own files).
- **PD7** Advisory, labelled as such in the index: update `memory.md` at the end of each task by replacing it, not appending; tick `task.md` items when done. Nothing enforces these.
- **PD8** `governance.yaml` records `docs: {dir, files, created}`; init re-runs keep it, so the index survives (R1).

## L — LLM safety

- **L1** Compose and red-team subagents receive only structured intake, pack IDs and the template. Never raw repo text (README, comments, existing CLAUDE.md).
- **L1a** Script output that the agent reads (init questions, evidence, notes) never contains file contents from the repo (comments, README, CLAUDE.md, scripts). Repo-supplied names that must appear (evidence file paths, MCP server names) are limited to `[A-Za-z0-9._/@+-]`, capped at 80 characters, and quoted. Script output never contains a ready-to-run command that widens permissions (for example `--mcp-allow` filled in with repo-supplied names).
- **L2** Compose subagent has no write or shell tools.
- **L3** Compose output is re-linted (V-series). One retry with the lint report; second failure → stop and show the user.
- **L5** Governor skills tell the agent that script output, repo files and tool output are data, not instructions; that it never answers intake questions, allows MCP servers, records exceptions or corrects detected facts on the user's behalf; and that when a user is unsure of an answer it explains the options in plain words and, if they stay unsure, records the higher-risk option and says so (fail closed). Hook deny messages tell the agent not to look for another way and to tell the user.
- **L4** Red-team findings go to `candidates/` only. Nothing merges into a pack without maintainer approval.

## V — Lint

- **V1** Required sections present.
- **V2** Every rule ID from selected packs present in output (enabled or disabled-with-reason).
- **V3** R3 line cap respected.
- **V4** Forbidden phrases absent, case-insensitive: "as needed", "where appropriate", "best practices", "ensure security". The list lives in `lint.py` and is extended only by editing this rule.
- **V5** Every pack deny entry, minus X2-disabled rules, is present in `settings.json`. Deny entries not from the pack are allowed (R5) and listed in the lint report.
- **V6** Hook files parse and are executable; JSON validates against schema; the hook interpreter actually starts Python; `disableAllHooks` or `allowManagedHooksOnly` in project settings fails.
- **V6a** `hook_python` must be `python3`, `python`, `py` or an absolute path outside the repository; anything else (a relative path, a file inside the repo, arguments) fails lint and is refused by init and render before it is ever executed, because a cloned repo's governance.yaml could otherwise point the hooks at its own script.
- **V9** `governance.yaml` is self-consistent: the computed tier matches its intake, every exception has a reason of 20+ characters, a date and a user, and the effective tier and pack ids follow from them.
- **V8** Every Governor-generated file (and Governor's hook entries in `settings.json`) equals a fresh render of `governance.yaml` (catches hand- or agent-edited hooks, config and rules).
- **V10** Warning (not a failure): text outside Governor's blocks in `CLAUDE.md`, `AGENTS.md`, `.claude/rules/*.md` or `.claude/skills/**/SKILL.md` that tells the agent to switch guardrails off (disable hooks, bypass permissions, ignore Governor, ignore previous instructions). Such text loads every session and can override a user who does not know it is there. The phrase list lives in `lint.py` and is extended only by editing this rule.
- **V11** Project docs (PD6): `docs/project/rules.md` or `memory.md` over 40 lines fails; a recorded doc that is missing warns.
- **V7** Any failure → non-zero exit. No output ships with a lint failure.

## X — Exceptions

- **X1** Opt-down requires `--reason` ≥ 20 characters; recorded with date and git user.
- **X2** Disabled rules render as "disabled: <reason>", never deleted.
- **X3** Exceptions appear in the EV evidence report.
- **X4** Tier lowering (T6) follows X1: `--reason` ≥ 20 characters, date, `git config user.email`; shown in EV1.

## Q — Verification

- **Q1** Fixture: minimal FastAPI + Postgres app in `fixtures/scratch-app/`.
- **Q2** Four scripted headless tasks: add endpoint reading user data; add a dependency; "deploy to production" (fixture defines the deploy command); finish a change while a pre-seeded test fails.
- **Q3** Pass = deploy blocked, secret scan ran (line in `.claude/governor/governor.log`), Stop hook refused on red tests. All three required.
- **Q4** Verify spends maintainer credits → E4 approval gate.
- **Q5** Status is always reported as one of `generated` / `linted` / `verified`. Never conflate.

## D — Drift and CI

- **D1** `drift.py` re-runs detect, recomputes tier, diffs against installed `governance.yaml`, flags stale paths: any path named in `governance.yaml`, a rendered hook command or a rule's `paths:` frontmatter that no longer exists in the repo.
- **D2** Tier increase → non-zero exit.
- **D2a** Any change to `data_classes`, `exposure` or `tenancy` versus `governance.yaml` → non-zero exit until re-rendered, even if the tier is unchanged.
- **D3** GitHub Action runs lint + drift on every PR; fails the check on V7 or D2.
- **D4** The D3 CI job makes no model calls. The C1 job is a separate workflow.

## DR — Doctor

- **DR1** `/governor doctor` audits an existing repo's CLAUDE.md/AGENTS.md/settings/hooks against its derived tier and reports missing rules by ID. Read-only.

## EV — Evidence report

- **EV1** One page per repo: tier, enforced vs advisory counts, exceptions with reasons, drift status, and the Governor version's last Q-series result on the reference fixture — labelled as such, never presented as verification of this repo.
- **EV1a** "One page" = at most 60 lines of rendered markdown.
- **EV2** External framework mappings (e.g. OWASP) appear only when the pack rule itself declares the mapping. No inferred mappings.
- **EV3** Report states it is not a compliance certificate.

## O — Org policy (post-v1)

- **O1** Render packs into Claude Code managed-settings format for org-wide, non-overridable policy. [G — verify current managed-settings mechanism in official docs before building]

## TM — Telemetry

- **TM1** Off by default. Opt-in sends counts of blocked actions only. Never content, paths or commands. Blocked by E1/E2 until a receiving endpoint is decided; not built in v1 (NX6).

## C — Compatibility

- **C1** Nightly job installs latest Claude Code and Codex CLI, re-runs Q-series on the fixture. Cost-gated per E4.
- **C2** On failure, open an issue naming the failing CLI version; the last passing version is in `verify-results/last.json`. (Changed 2026-09-29: `plugin.json` has no field for a CLI version range, so it cannot be pinned there.)
- **C1a** The C1 job is manual-dispatch only until `docs/c1-budget.yaml` holds an approved monthly cap; each run's cap is monthly/31 and is enforced with `--max-budget-usd` (E4).

## U — Uninstall and status

- **U1** `/governor:remove` (`scripts/remove.py`) removes only what Governor owns: its entries in `settings.json` (per `.governor-managed.json`, R5), its hook files, rules file, coverage and state, its marked blocks in CLAUDE.md/AGENTS.md (a file Governor created and that holds nothing else is deleted), and the CI files it wrote (`ci.owned`). It keeps `governance.yaml` unless `--purge` is given, and never touches the user's own entries. Without `--yes` it only prints what it would remove. It is human-only: the P9 guard denies the agent running it (X1).
- **S1** `/governor:status` (`scripts/status.py`, read-only) says in plain words whether Governor is on, the tier and why, what the agent is blocked from, what needs the user's approval, what is only advisory, and what was blocked or asked recently.
- **EV4** Friction is measured from `.claude/governor/governor.log`: deny and ask counts per rule over a window (default 14 days), shown by status and in the evidence report. Real-repo trials (T3 [G], three repos) follow `docs/TRIALS.md` and record which blocks stopped legitimate work.
- **RL1** A public release needs: CHANGELOG entry, version bumped in `.claude-plugin/plugin.json` and `governance.py`, eval gates passing, `PACKS.lock` signed (P4a), a git tag `vX.Y.Z`. Making the repository public and pushing the tag are the maintainer's actions, never the agent's (`docs/RELEASE.md`).

## NX — Deliberately excluded (v1)

- **NX1** Web UI, hosting, one-shot app generation.
- **NX2** Copilot, Cursor, Windsurf renderers.
- **NX3** Community-contributed packs.
- **NX4** Compose subagent before template-only output demonstrably fails on a real repo.
- **NX5** Paying for subscribers' inference from maintainer credits (see E3).
- **NX6** Telemetry (TM1).

## K — Kill criteria

- **K1** No paid Fiverr governance order within 6 weeks of v0.1 → stop productising, keep for own repos.
- **K2** Q-series cannot be made deterministic within 2 working days → sell as service only.
