# Session prompts — Claude Code (cloud)

Rules for every session:
- One phase per session. Start a new session for the next phase.
- Paste only the line for the phase. Claude reads the rest from the repo.
- Session ends at the exit check: commit on a branch, open a PR, stop. You review the PR before the next phase.
- If a session starts rewriting SPEC.md or drifting into another phase, stop it.

---

## Phase 0 — Kickoff review (no code)
Read CLAUDE.md, SPEC.md, docs/BUILD_PLAN.md, docs/BACKGROUND.md, docs/PROMPTS.md and .claude/settings.json. Do not write code. Report: (1) contradictions or gaps between SPEC rules, (2) every rule tagged [G] and what would verify it, (3) any SPEC rule that cannot be tested as written, (4) anything about current Claude Code plugins, hooks or settings that the spec assumes and you cannot confirm. Propose edits to SPEC.md as a diff but do not apply them. Stop.

## Phase 1 — Intake
Read CLAUDE.md, SPEC.md and docs/BUILD_PLAN.md. Do Phase 1 only (rules I1–I5). Build intake.schema.json, scripts/detect.py, scripts/ask.py with pytest tests. detect.py must work on three synthetic fixture repos you create under fixtures/detect/ (FastAPI+Postgres with auth; React+Vite static site; Node API with Stripe). Every function docstring cites its rule ID. Stop when tests pass; commit to branch phase-1 and open a PR. Do not start Phase 2.

## Phase 2 — Tiers and packs
Read CLAUDE.md, SPEC.md, docs/BUILD_PLAN.md. Do Phase 2 only (T1–T6, P1–P8). Build tiers.yaml, packs/tier1|tier2|tier3/fastapi-postgres/claude-code.yaml, scripts/select.py, scripts/sign_pack.py (sha256 hash pinning; real signing can come later — note that in a TODO citing P4). Tests must assert: tier-N pack is a superset of tier N-1 (P3); every rule has enforcement and mechanism fields (P2); base pack contains every P6 item; every rule ID appears in SPEC.md. Stop at green tests; commit to phase-2, open PR.

## Phase 3 — Render, lint, exceptions
Read CLAUDE.md, SPEC.md, docs/BUILD_PLAN.md. Do Phase 3 only (R1–R6, V1–V7, X1–X3). Build governance.yaml writer, Jinja renderers for CLAUDE.md, .claude/settings.json, .claude/rules/, .claude/hooks/*.py, scripts/lint.py, scripts/exceptions.py. Hooks are stdlib-only (P5); test each hook with fixture stdin JSON for block and allow cases. Test R5 by installing into a fixture that already has a settings.json and asserting its existing keys survive. Stop at green tests + clean lint of rendered output; commit to phase-3, open PR.

## Phase 4 — Verify (run LOCALLY, not in cloud)
Build only: fixtures/scratch-app/ and scripts/verify.py (Q1–Q5). Do NOT execute verify.py in this session. Stop after building; commit to phase-4, open PR. Sandhya runs verify locally after approving the cost.

## Phase 5 — Doctor, drift, CI
Read CLAUDE.md, SPEC.md, docs/BUILD_PLAN.md. Do Phase 5 only (DR1, D1–D4). Build scripts/doctor.py, scripts/drift.py, .github/workflows/governor.yml. The workflow must make no model calls (D4). Stop at green tests; commit to phase-5, open PR.

## Phase 6 — Evidence report
Read CLAUDE.md, SPEC.md, docs/BUILD_PLAN.md. Do Phase 6 only (EV1–EV3). Build scripts/report.py producing a one-page markdown report from governance.yaml + lint + drift + last verify status. No framework mappings unless the pack rule declares one explicitly (EV2). Stop at green tests; commit to phase-6, open PR.

## Phase 7 — Package
Read CLAUDE.md, SPEC.md, docs/BUILD_PLAN.md. Do Phase 7 only (E1, E7). Package as a Claude Code plugin: .claude-plugin/plugin.json, commands /governor:init, /governor:except, /governor:drift, /governor:doctor, a skill wrapping the scripts, and a private marketplace.json. Add the Codex AGENTS.md renderer. Check the current plugin manifest format in the official Claude Code docs before writing it; cite the doc URL in a comment. Stop; commit to phase-7, open PR.
