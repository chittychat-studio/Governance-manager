# Governor — Background and positioning

Why this exists, what it competes with, and what was deliberately rejected.
Research date: 2026-09-29. Re-check competitors before any launch or pricing decision.
No figures here are to be reused in marketing copy without re-verifying the source.

## Problem
Developers using coding agents forget the same nuances every project: security rules, guardrails,
hooks, minimal permissions, settings.json, a lean CLAUDE.md, and what to deliberately exclude.
Vibe coders don't know these exist at all.

## Directions considered and rejected

### 1. Subscription for a description → system prompt / CLAUDE.md generator — REJECTED
Generation is free and built into the host tools:
- Claude Code `/init` does phased CLAUDE.md + optional skills/hooks setup.
  https://exampleconfig.com/tools/claude-md-generator (describes the /init v2 flow)
- ClaudeForge (open source): generator + guardian agent, hooks, 150-line cap, drift audit.
  https://github.com/alirezarezvani/claudeforge
- agentsync: converts/syncs AGENTS.md, CLAUDE.md, .cursorrules etc.; scaffolds AGENTS.md from a spec.
  https://github.com/PanisHandsome/ai-rules-sync
- MarkdownMe: free CLAUDE.md generator, reviewer, converter, token counter.
  https://markdownme.com/tools/claude-md-generator
- Methodology plugins, free: Superpowers (official Claude + Codex marketplaces), GitHub spec-kit plugin.
  https://github.com/obra/superpowers · https://github.com/github/spec-kit/pull/1451
Reasons: output is a file the user owns (no recurrence); platform absorbs the feature; vibe coders
are the least willing payers for governance.

### 2. One-shot idea → hosted full-stack app with guardrails — REJECTED
Competes directly with Lovable, Bolt, v0, Base44, Replit Agent. Build step is described as
commoditised by independent comparisons (https://technically.dev/posts/vibe-coding-tool-comparison).
Incumbents already ship security scans/guardrails (Lovable scan on publish; Replit security scanner).
Hosting adds per-user inference cost and breach liability, and violates our human-gate / fail-closed
standards.

## Adjacent security tools (free or OSS unless noted)
- Vibe Owl — free local VS Code security extension. https://vibeowl.dev/best-vscode-security-extensions
- drift-analyzer — structural erosion + pre-session guardrails, vibe-coding profile. https://pypi.org/project/drift-analyzer/
- vibe-guard — CLI security rules for vibe coders. https://github.com/Devjosef/vibe-guard
- vibeward — scanner for Lovable/Bolt/v0/Supabase apps (RLS, exposed keys). https://github.com/JSiapoDEV/vibeward
- vibe-hardening — 30+ rules tuned per AI generator. https://github.com/vibe-hardening/cli
- AppGuardrail — rules + scanner; **sells a monthly review retainer** (closest paid model). https://pypi.org/project/appguardrail/
- xlogs — read-only scanner, explicitly not a compliance artefact. https://github.com/damnepic/xlogs-cli
- Paid, team-focused: Snyk, GitGuardian.

## Chosen position
Governor = enforced, verified, drift-checked agent governance — not better prose.
Differentiators vs the above:
1. Controls derived from facts (tier lookup); user never picks their own guardrails (SPEC I5).
2. Every rule labelled enforced vs advisory, with per-agent coverage table (P2, R6).
3. Layered enforcement: deny rule + PreToolUse hook (P7).
4. Verification against a real agent run, not just generation (Q-series).
5. CI gate independent of which agent wrote the code (D3).
6. `doctor` for existing repos (DR1).
7. Client-facing evidence report — BA/PM strength (EV).
8. Later: domain packs (ServiceNow, UK GDPR) and org managed-settings policy (O1).

## Monetisation path (ranked)
1. Manual Fiverr service: governance setup for a repo, fixed fee. Validates demand; captures real rules.
2. Agency retainer: monthly review/drift report per client repo (AppGuardrail-style model).
3. Paid domain packs.
4. Team plan: CI gate + org policy + evidence reports.
Open question [G]: whether Claude Code / Codex marketplaces offer any billing rail. Verify before pricing.

## Known risks
- Platform release cadence breaks renders → nightly compatibility job (C1) is a real running cost.
- Distributing executable hooks = supply-chain risk → signed packs (P4).
- Prompt injection via repo content → LLM never sees raw repo text (L1).
- False sense of security → honest enforced/advisory labels; "not a compliance certificate" (EV3).

## Kill criteria
See SPEC K1, K2.
