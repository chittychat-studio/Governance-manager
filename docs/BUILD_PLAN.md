# Governor — Build plan

Order is fixed. Do not start a phase until the previous one's exit check passes.

| Phase | Build | Rules | Exit check |
|---|---|---|---|
| 0 | SPEC.md + CLAUDE.md (done) | all | Rules reviewed by Sandhya |
| 1 | `intake.schema.json`, `detect.py`, `ask.py` | I1–I5 | Detect fills ≥ 4 required fields on 3 synthetic fixtures (cloud); then on DeckForge, JobPilot, market-api run locally |
| 2 | `tiers.yaml`, tier-3 fastapi-postgres claude-code pack, `select.py`, pack signing | T1–T6, P1–P8 | Every pack rule ID exists in SPEC; tier table matches your judgement on 3 repos |
| 3 | `governance.yaml`, renderers, `lint.py`, `exceptions.py` | R1–R6, V1–V7, X1–X3 | Rendered output passes lint; installs into fixture without clobbering existing settings |
| 4 | Fixture app, `verify.py` (headless) | Q1–Q5 | 3/3 tasks pass twice in a row — built in cloud, **run locally**, approval first |
| 5 | `/governor doctor`, GitHub Action, drift | DR1, D1–D4 | Doctor flags gaps on an old repo; Action fails a PR that adds a data class |
| 6 | Evidence report | EV1–EV3 | One-page report for DeckForge a client could read |
| 7 | Package as Claude Code plugin; Codex AGENTS.md renderer | E1, E7 | Installs from a private marketplace on a clean machine |
| 8 | First paid Fiverr governance order | K1 | Paid, delivered, feedback captured as candidate rules |
| later | Compose subagent, red-team subagent, cost pack tuning, org managed settings, telemetry | NX4, L1–L4, O1, TM1 | Only after Phase 8 |

## Where credits are spent
- Yours: Claude Code sessions to build it, Phase 4 verify, C1 nightly job.
- Subscribers': compose/red-team subagents in their own session (E3).
- Nobody's: detect, tier, select, render, lint, drift, doctor, CI (E2, D4).
