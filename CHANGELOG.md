# Changelog

Status words follow SPEC Q5: generated / linted / verified. Nothing below is "verified" in a live session yet.

## 0.2.0 (unreleased)

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

## 0.1.0

Phases 1–7: intake, tiers, packs, render, hooks, lint, drift, doctor, evidence report, CI gate, hardening rounds 1–3,
eval suite and edge-case suite.
