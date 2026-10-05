# Changelog

Status words follow SPEC Q5: generated / linted / verified. Nothing below is "verified" in a live session yet.

## 0.2.0 (unreleased)

- **Project docs, optional (PD1-PD8, V11).** `/governor:docs` asks 8 plain questions and creates `docs/project/`
  PRD, architecture, rules, design, task and memory files from the answers (template only, no model writes them).
  Created once, then the user's; never overwritten, kept on remove. Lean loading: only `rules.md` and `memory.md` are
  imported every session and lint fails either above 40 lines; `design.md` loads only for UI files; the rest are
  read on demand.
- **Windows test command paths (I1f).** See PR #16.
- **Review round fixes (PD4, PD6, V11, I1f, I1b).** Always-loaded project docs are checked on every Edit/Write
  (no `@` import lines, no guardrail-off text, 40 lines / 4,000 characters) and shell writes to them are blocked;
  a repo-shipped unsafe `rules.md` is refused before import; docs.py refuses symbolic links and never writes outside
  the repo. "Could not start" now means the test program was not found; exit 127 from inside the tests is reported
  as failing. init's test-command check no longer writes state into the current folder.

For vibe coders: any project, no extra installs, plain words.

- **Every project gets rules (P1a, P11).** Stack-neutral `generic` packs hold all base rules. The `node` family
  covers Next.js, React, Vite, Node, Supabase and Firebase. `fastapi-postgres` stays. Stacks without a family get
  `generic` instead of a refusal. New: deploy asks for Firebase, Wrangler and Supabase; destructive-migration asks
  for Prisma, Supabase and Drizzle; the secret scan flags server secrets in `NEXT_PUBLIC_` / `VITE_` / `EXPO_PUBLIC_` /
  `REACT_APP_` variables; advisory: keep Supabase RLS on.
- **No PyYAML (E8).** Runtime is Python 3.11+ standard library only (`scripts/miniyaml.py`, checked against PyYAML on
  every repo YAML file and by fuzzing). Plain message when Python is missing or old.
- **Plain questions (I5b, I1e).** Every option has a one-line explanation. "Not sure" records the safer answer and
  the report lists it as assumed. The stack question offers JavaScript / Python / not sure.
- **Uninstall (U1).** `/governor:remove` shows the plan; the user confirms with `--yes`. It removes only what
  Governor owns and keeps `governance.yaml` unless `--purge`.
- **Plain block messages and status (P12, S1).** Every block says why and what the user can do. `/governor:status`
  summarises protection and recent blocks.
- **Friction (EV4).** Deny/ask counts per rule from the hook log, in status and the evidence report;
  `docs/TRIALS.md` for real-repo trials.
- **Signing (P4a).** Ed25519 (RFC 8032, standard library, test vectors) over `PACKS.lock`; installs refuse a
  missing or bad signature once `packs/SIGNING_KEY.pub` exists. Not yet signed: the maintainer creates the key.
- Version 0.2.0. Existing installs: re-run `/governor:init` (pack pins changed; lint says so).
- **Real-repo trials, round 1 (T3, EV4).** `scripts/trial.py` on four real repos: 149 documented commands, friction
  down from 10 to 0 after the fixes below, every attack stopped (docs/TRIALS.md).
  - Shell comments are ignored before matching (P7b).
  - Windows `copy` / `Copy-Item .env.example .env` is allowed (P6a).
  - Restoring declared dependencies no longer asks while manifests are unchanged in git; editing a manifest makes
    restores ask again (P10a).
- `scripts/release_check.py` runs every release check and lists the maintainer's remaining steps (RL1).

## 0.1.0

Phases 1–7: intake, tiers, packs, render, hooks, lint, drift, doctor, evidence report, CI gate, hardening rounds 1–3,
eval suite and edge-case suite.
