# Governor

Claude Code plugin that turns a repo + short intake into enforced agent governance
(settings, hooks, rules, CLAUDE.md/AGENTS.md). Full rules: `SPEC.md`. Build order: `docs/BUILD_PLAN.md`. Why/competitors: `docs/BACKGROUND.md`. Session prompts: `docs/PROMPTS.md`.

## Non-negotiables
- Every change cites a SPEC rule ID in the commit message. No rule → write the rule first.
- Scripts in `scripts/` make zero network calls and zero model calls (E2, D4).
- Never add an API key, SDK client or model call to Governor code. LLM work = subagent in the user's session (E3).
- Hooks: Python stdlib only (P5). Test each with a fixture stdin JSON.
- Never write to `~/.claude/` (E6). Merge settings.json, never overwrite (R5).
- Report status as generated / linted / verified. Green unit tests ≠ verified (Q5).

## Cost gate
Before any command that spends credits (verify, nightly, compose testing): print estimate, stop, wait for approval (E4).

## Commands
- `python -m pytest` — unit tests
- `python scripts/lint.py <out_dir>` — V-series lint
- `python scripts/verify.py` — Q-series, spends credits, approval required
- `python scripts/init.py <repo> --questions` then `--answers a.json` — full install pipeline
- `python scripts/sign_pack.py` — re-pin packs after editing any pack YAML (P4)
- `python scripts/eval.py` — eval gates (evals/thresholds.yaml); must pass before any PR

## Do not
- Feed raw repo text to any subagent (L1).
- Auto-merge red-team candidates (L4).
- Build anything listed under NX in SPEC.md.

## Decisions log
- 2026-09-29: Plugin inside Claude Code; inference billed to user's own session, not maintainer credits (E3, NX5).
- 2026-09-29: Controls derived by tier lookup; user never asked which guardrails they want (I5).
- 2026-09-29: Every rule labelled enforced vs advisory; coverage table shipped in output (P2, R6).
- 2026-09-29: Packs signed and hash-pinned (P4). LLM never sees raw repo text (L1).
- 2026-09-29: Phase 0 review → SPEC v0.3. v1 packs are hash-pinned only; say "signed" only after P4a (P4, P4a). Telemetry out of v1 (NX6). Settings ownership tracked in `.claude/.governor-managed.json`, not file headers (R4).
- 2026-09-29: Kill criteria K1, K2 adopted.
- 2026-09-29: Production-readiness review (3 independent reviewers) → hardening: PowerShell coverage, fail-closed logging, lint V8 integrity, detected facts correctable upward only (P7, V8, I3a, T6). Regression cases live in tests/test_adversarial.py and tests/test_batch2.py; add to them, never delete.
- 2026-09-29: Built in Claude Code cloud sessions, one phase per session, PR per phase (docs/PROMPTS.md). Verify (Phase 4) runs locally, not in cloud.
