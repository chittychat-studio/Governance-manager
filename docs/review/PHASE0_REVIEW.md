# Phase 0 — Kickoff review

Date: 2026-09-29. Read-only review. No code written. SPEC.md is **not** modified; proposed edits are in `phase0-spec.patch` (apply with `git apply docs/review/phase0-spec.patch`).

Doc checks are against code.claude.com as fetched on 2026-09-29. Where a claim is marked "unconfirmed", the docs page I read did not state it either way.

## 1. Contradictions and gaps between rules

| # | Rules | Problem | Proposed fix (in patch) |
|---|---|---|---|
| 1 | V5 vs R5 | V5 "deny list matches pack exactly" fails whenever R5 preserves a user's existing deny entries. Every real install breaks lint. | V5 → pack denies ⊆ settings denies; extras reported. |
| 2 | R4 vs V6/R5 | JSON has no comments, so `settings.json` cannot carry the header; and a merged file is not "generated". | R4 applies to wholly-generated files; settings ownership via `.governor-managed.json`. |
| 3 | P6 vs I1 | Base pack requires a Stop hook running `test_cmd`, but `test_cmd` is optional. | Make `test_cmd` required (7 required fields = I4 cap; optionals only with leftover budget). |
| 4 | D2 vs BUILD_PLAN Phase 5 | Exit check "Action fails a PR that adds a data class" — D2 only fails on tier *increase*. Adding `pii` to a tier-3 repo passes. | Add D2a: any change to data_classes/exposure/tenancy fails until re-rendered. |
| 5 | E4 vs C1 | A nightly job cannot "wait for approval". | Unattended runs need a pre-approved monthly cap; refuse when exceeded. |
| 6 | D4 vs C1 | C1 runs Q-series (model calls) in CI; D4 says "the CI job makes no model calls". | D4 scoped to the D3 job; C1 is a separate workflow. |
| 7 | EV1 vs Q-series | Verify runs on the fixture, not on client repos, so a client repo has no "last verify status". Reporting one would be a misleading claim in a client-facing document. | EV1 reports the Governor version's fixture result, labelled as such. |
| 8 | P4 vs Phase 2 prompt | P4 says "signed"; Phase 2 builds sha256 pinning only. Key custody and offline verification are undefined. | Split P4 (hash pin, v1) / P4a (signing, deferred; never say "signed" until then). |
| 9 | T6 vs X-series | T6 points to X for tier lowering; X1–X3 only cover rule opt-down. | Add X4. |
| 10 | T2–T5 | No precedence when several match; enums for data_classes/exposure/tenancy undefined; `auth` as a data class undefined. An unrecognised value falls through to T5 → tier 1 (fails open). | T0 highest-wins; I1a closed enums; unknown → refuse. |
| 11 | TM1 vs E1/E2 | Opt-in telemetry needs a receiving endpoint = hosted backend. | Move to NX6 for v1. |
| 12 | E5 | Compose caching has no phase; compose itself is NX4. | Mark E5 as applying only after NX4. |
| 13 | R3 vs `.claude/rules/` | Rules without `paths:` frontmatter load every session like CLAUDE.md. A 150-line cap on CLAUDE.md alone can be bypassed by moving text into rules. | Cap applies to CLAUDE.md + unscoped rules combined. |
| 14 | K1 | "Shelve SaaS" — there is no SaaS in scope (E1, NX1). | Wording. |
| 15 | Q2 vs Q3 | Q3 requires "Stop hook refused on red tests" but none of the Q2 tasks produces red tests. "Deploy" command undefined on the fixture. "Secret scan ran" has no observable evidence. | Q2 task 4 with a pre-seeded failing test; fixture defines deploy; scan hook writes to `.claude/governor.log`. |

Not a spec change, but note: the Phase 3 prompt says "Jinja renderers". Jinja2 is third-party. P5 only restricts hooks, so this is allowed, but the plugin then needs a pip install on the user's machine at render time. Decide before Phase 3 whether `string.Template` is enough.

## 2. Rules tagged [G] or [L] and what would verify them

| Rule | Tag | Verification |
|---|---|---|
| T3, T4 | [G] | Before running `select.py`, write down your own tier for DeckForge, JobPilot and market-api (blind). Then compare with the tool's result. Any mismatch → fix the table, not the judgement. Three repos is thin; add one Fiverr-style repo if you can. |
| O1 | [G] | Docs describe endpoint-managed (`managed-settings.json`) and server-managed settings. The first was confirmed via the memory docs (`claudeMd` key in managed settings). The server-managed claim came from a subagent and I did **not** check it myself. Re-check at O1 start. |
| E6 | [L] | Unconfirmed from docs in this session. Direct test: put a deny rule in local `~/.claude/settings.json`, open a cloud session, try the denied action. |
| P7 | [L] → [C] | Confirmed: the permissions doc says Bash rules match command text only and are "not a security boundary"; a PreToolUse hook that exits 2 blocks before the rules are evaluated. |
| BACKGROUND billing rail | [G] | Plugin manifest reference has no pricing or payment fields (only a free-form `metadata` object). No billing rail found. Treat monetisation as off-marketplace. |
| E7 (proposed) | [G] | Whether Codex reads a *project-level* config file. Needs an OpenAI source; I did not verify it. |
| P6 Stop loop guard (proposed) | [G] | The hooks page I fetched did not mention a `stop_hook_active` input field. Confirm the guard mechanism before building the Stop hook, or the hook can trap a session in a loop. |

## 3. Rules that cannot be tested as written

- **R3** "contains only rules the agent would get wrong without it" — judgement. (Patch: content restricted to pack text + commands + exceptions.)
- **P6** "cloud credential paths" (no list), "deny or ask" (which one?). (Patch: explicit list; deny vs ask fixed per item.)
- **P7** "critical deny" undefined. (Patch: every P6 deny item.)
- **P8** N and "known paid-API CLIs" undefined. (Patch: default 3; `paid_cli` list is a pack field.)
- **V4** "best practices without a concrete rule" — needs a concrete check. Suggest: the phrase is banned outright.
- **D1** "stale paths" undefined.
- **EV1** "one page" — define as a line or section limit.
- **EV2** "clearly matches" — suggest: a mapping exists only if the pack rule declares it (the Phase 6 prompt already says this; the SPEC should too).
- **E4** "estimated cost" — no estimation method. Suggest: fixed per-task token budget × current price, printed with its source.
- **I5** — testable only if questions come from a fixed bank in `ask.py`, each mapped to an I1 field. Add that as I5a if you agree.
- **K1, K2** — business criteria, not code-testable. That's fine; just don't put them in the test suite.

## 4. Claude Code assumptions

| Assumption | Status | Source |
|---|---|---|
| `.claude/rules/*.md` loaded | Confirmed. No `paths:` → loaded every session; with `paths:` → loaded when matching files are read. | docs/en/memory |
| Deny → ask → allow precedence | Confirmed, first match in that order wins; ask beats a more specific allow. | docs/en/permissions |
| `Bash(x *)` matches bare `x` | Confirmed (when trailing `*` is the only wildcard). So `Bash(python scripts/verify.py *)` in ask **does** catch bare `python scripts/verify.py`, and beats the `python scripts/*` allow. | docs/en/permissions |
| Bash deny catches variants | **No.** `/bin/rm`, `bash -c '…'`, `git -C . push` are not matched. Supports P7. | docs/en/permissions |
| Read deny covers `cat .env` | Partly. Covers recognised file commands (`cat`, `head`, `tail`, `sed`, `tee`) and redirects; not `grep -r` or a Python script that opens the file. | docs/en/permissions |
| Hook `allow` overrides deny rules | No — deny/ask rules still apply. A hook exit 2 blocks even when an allow rule matches. | docs/en/permissions |
| Stop hook can block | Confirmed (exit 2 or `decision: block`). | docs/en/hooks |
| `$CLAUDE_PROJECT_DIR` in hooks | Confirmed. | docs/en/hooks |
| Plugin manifest `.claude-plugin/plugin.json` | Confirmed; optional. Components namespaced `plugin-name:component`, so `/governor:init` is correct. | docs/en/plugins-reference |
| Plugin can ship hooks, skills, commands, agents | Confirmed. `commands/` is described as legacy — "prefer `skills/`". Phase 7 prompt should say skills. | docs/en/plugins-reference |
| Plugin can ship permission deny rules | **No.** Plugin `settings` honours only `agent` and `subagentStatusLine`. Governor must write deny rules into the project's `.claude/settings.json` — which E6/R2 already do. A plugin-only install gives hooks but **no** deny layer. | docs/en/plugins-reference |
| Plugin `bin/` directory | Plugins with a top-level `bin/` are not installed by claude.ai or Cowork. Keep scripts in `scripts/`. | docs/en/plugins-reference |
| Cloud sessions read project `.claude/settings.json`, not `~/.claude/` | Unconfirmed by me (E6 above). | — |
| Codex reads `AGENTS.md` | Claude Code itself now reads `AGENTS.md` when no `CLAUDE.md` exists. Codex behaviour not verified from an OpenAI source here. | docs/en/memory |
| Marketplace billing | None found. | docs/en/plugins-reference |

## Observations on this repo's `.claude/settings.json` (not spec changes)

- This session started on an empty repo, so **it ran without these guardrails**. Phase 1 onward will load them.
- `Bash(pip install *)` is auto-allowed. That lets a build session install any package unprompted, which is a supply-chain hole for a governance tool. Suggest moving it to `ask`.
- `curl`/`wget` deny does not stop `python -c "urllib…"` (see Bash-variant row). There are no hooks in the build repo itself, so the build session relies on the layer P7 says is not dependable. Acceptable for a private build, but inconsistent with the product's own doctrine.
