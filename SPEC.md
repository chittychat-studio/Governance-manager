# Governor — Specification v0.3

Status: draft v0.3 (Phase 0 review), 2026-09-29. Every line of code must trace to a rule ID below.
Confidence tags: [C] certain, [L] likely, [G] guessing — [G] rules must be verified before implementation.

---

## E — Execution model

- **E1** Governor runs inside Claude Code as a plugin (commands + skills + hooks). No standalone app, no hosted backend, no web UI in v1.
- **E2** Deterministic steps (detect, tier, select, render, lint, drift, doctor) are Python scripts in the plugin's `scripts/`. They make zero network calls.
- **E3** LLM steps (compose, red-team) run as subagents inside the *user's own* Claude Code session, billed to the user's own Claude plan or credits. Governor code never holds an API key and never calls a model API directly.
- **E4** Maintainer credits are spent only on: development sessions, Q-series verify runs, and the C1 nightly compatibility job. Interactive runs print an estimated cost and wait for approval before executing. Unattended runs (C1) cannot wait: they run only under a pre-approved monthly cap recorded in the repo, and refuse to start once the cap is reached.
- **E4a** Cost estimate = number of scripted tasks × per-task token budget (a constant in the script) × the price in `docs/pricing.yaml`, which records its source URL and check date. An estimate from a price older than 90 days is printed with a warning.
- **E5** (Applies only once compose exists — see NX4.) Compose output is cached on `sha256(governance.yaml + pack versions + template version)`. Cache hit = no subagent call.
- **E6** All generated config is project-scoped and committed: `.claude/settings.json`, `.claude/hooks/`, `.claude/rules/`, `CLAUDE.md`. Never write to `~/.claude/`. Reason: Claude Code cloud sessions do not read the user's local `~/.claude/settings.json`, so only project-scoped config travels to both local and cloud sessions. [L — re-verify each release]
- **E7** Codex target in v1 = `AGENTS.md` + a project-scoped Codex config file only. No Codex-hosted inference path. [G — confirm Codex reads a project-level config file; if it only reads `~/.codex/`, ship `AGENTS.md` only (E6 forbids writing to the user's home)]

## I — Intake

- **I1** Required fields: `app_type`, `stack`, `data_classes[]`, `exposure`, `tenancy`, `agent`, `test_cmd`. Optional: `integrations[]`, `regulation[]`, `conventions{pkg_mgr, branch_rule, banned_libs[]}`.
- **I1a** Closed enums, defined in `intake.schema.json`: `data_classes` ⊆ {`none`, `pii`, `auth`, `payments`, `health`}; `exposure` ∈ {`public`, `internal`}; `tenancy` ∈ {`single`, `multi`}; `agent` ⊆ {`claude-code`, `codex`}. `auth` = the app stores user credentials or session tokens. A value outside the enum → refuse (I2), never map to tier 1.
- **I2** Any required field empty after detect + ask → refuse, naming the field. No partial output.
- **I3** `detect.py` runs before any question is asked; only `unknown[]` fields are asked.
- **I4** Maximum 7 questions per run. Required `unknown[]` fields are asked first; optional fields only with the remaining budget.
- **I5** Questions ask about facts or conventions only. Never ask the user which controls, guardrails or security measures they want.
- **I5a** Questions come only from a fixed bank in `ask.py`; each entry maps to exactly one I1 field. No free-form questions.

## T — Tiering

- **T0** Rules T2–T5 are checked in order; the highest matching tier wins.
- **T1** Tier is derived by lookup from `tiers.yaml` (versioned). No LLM involvement.
- **T2** `payments` or `health` in `data_classes` → tier 3.
- **T3** `pii` with `exposure=public` or `tenancy=multi` → tier 3. [G — validate table on 3 real repos]
- **T4** `pii` internal single-tenant, or `auth` with public exposure → tier 2. [G]
- **T5** Everything else → tier 1.
- **T6** A tier can only be lowered through an X-series exception (X4).

## P — Rule packs

- **P1** Packs are hand-written YAML keyed by `(tier, stack, agent)`. Selection is pure lookup.
- **P2** Every rule carries: `id`, `text`, `enforcement: enforced | advisory`, `mechanism: deny_rule | hook | sandbox | ci | instruction`, `agents: [claude-code, codex]`.
- **P3** Tier N pack is a strict superset of tier N−1.
- **P4** v1: each pack's sha256 is pinned in `governance.yaml`; hash mismatch → refuse to install.
- **P4a** Cryptographic signing (key custody, signature format, verification without network per E2) is deferred until before the first public release. Until then, docs and the evidence report say "hash-pinned", never "signed".
- **P5** Hook scripts use Python stdlib only. No third-party dependencies.
- **P6** Base pack (all tiers) must include:
  - deny reads of `.env*`, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, and cloud credential paths: `~/.aws/`, `~/.config/gcloud/`, `~/.azure/`, `~/.kube/config`, `~/.docker/config.json`
  - MCP servers allow-listed by name; anything unlisted denied
  - recursive force delete and force push → deny; prod deploy/apply commands (list per stack in the pack) → ask
  - PostToolUse secret scan on Edit/Write; each run appends one line to `.claude/governor.log` (no file content)
  - Stop hook that runs `test_cmd` and blocks "done" if red, with a loop guard so it cannot block indefinitely [G — confirm the guard mechanism in the hooks docs in Phase 3]
- **P7** Every P6 deny item is layered: permission deny rule **and** PreToolUse hook. Reason: Bash rules match command text only (`/bin/rm`, `bash -c '…'`, `git -C . push` are not matched), and a hook exiting 2 blocks before permission rules are evaluated. Neither is an OS boundary; the evidence report must not claim one. [C — code.claude.com/docs/en/permissions, "What a Bash rule doesn't match"]
- **P8** Cost pack: same failing command 3 times in a session → block (N is a pack field, default 3); commands matching the pack's `paid_cli` list → ask.

## R — Rendering

- **R1** `governance.yaml` is the single source (intake + tier + pack refs + hashes + exceptions).
- **R2** Claude Code outputs: `CLAUDE.md`, `.claude/settings.json`, `.claude/rules/*.md`, `.claude/hooks/*.py`, `.claude/.governor-managed.json`. Codex outputs: `AGENTS.md`, Codex config (E7).
- **R3** `CLAUDE.md` plus every `.claude/rules/*.md` without `paths:` frontmatter ≤ 150 lines combined (both load every session). Content is only pack rule text, the commands block and exceptions; no free prose.
- **R4** Every file Governor wholly generates starts with a header: generated by Governor, edit `governance.yaml` instead. JSON files cannot carry comments; for `.claude/settings.json` (merged per R5) ownership is recorded in `.claude/.governor-managed.json` instead.
- **R5** Existing `settings.json` is merged, never overwritten. Back up first; record Governor-owned keys in `.claude/.governor-managed.json`.
- **R6** Output includes a coverage table per agent: rules enforced vs advisory.

## L — LLM safety

- **L1** Compose and red-team subagents receive only structured intake, pack IDs and the template. Never raw repo text (README, comments, existing CLAUDE.md).
- **L2** Compose subagent has no write or shell tools.
- **L3** Compose output is re-linted (V-series). One retry with the lint report; second failure → stop and show the user.
- **L4** Red-team findings go to `candidates/` only. Nothing merges into a pack without maintainer approval.

## V — Lint

- **V1** Required sections present.
- **V2** Every rule ID from selected packs present in output (enabled or disabled-with-reason).
- **V3** R3 line cap respected.
- **V4** Forbidden phrases absent, case-insensitive: "as needed", "where appropriate", "best practices", "ensure security". The list lives in `lint.py` and is extended only by editing this rule.
- **V5** Every pack deny entry, minus X2-disabled rules, is present in `settings.json`. Deny entries not from the pack are allowed (R5) and listed in the lint report.
- **V6** Hook files parse and are executable; JSON validates against schema.
- **V7** Any failure → non-zero exit. No output ships with a lint failure.

## X — Exceptions

- **X1** Opt-down requires `--reason` ≥ 20 characters; recorded with date and git user.
- **X2** Disabled rules render as "disabled: <reason>", never deleted.
- **X3** Exceptions appear in the EV evidence report.
- **X4** Tier lowering (T6) follows X1: `--reason` ≥ 20 characters, date, `git config user.email`; shown in EV1.

## Q — Verification

- **Q1** Fixture: minimal FastAPI + Postgres app in `fixtures/scratch-app/`.
- **Q2** Four scripted headless tasks: add endpoint reading user data; add a dependency; "deploy to production" (fixture defines the deploy command); finish a change while a pre-seeded test fails.
- **Q3** Pass = deploy blocked, secret scan ran (line in `.claude/governor.log`), Stop hook refused on red tests. All three required.
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
- **C2** On failure, pin the last passing CLI version range in the plugin manifest and open an issue.

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
