# Governor evidence report: example-api

2026-09-29 · Governor 0.1.0 · status: **linted**

> This report is not a compliance certificate. It describes agent configuration only.

## Tier

Tier 3, decided by T3. Data classes: auth, pii; exposure: public; tenancy: single.

Test command run by the Stop hook: `python -m pytest`

## Rules

| Agent | Enforced | Advisory | Disabled |
|---|---|---|---|
| claude-code | 15 | 2 | 0 |

## Exceptions

- None.

## Checks

- Lint (V1-V7): pass
- Drift (D1-D2a): none
- Q-series on Governor's reference fixture: not run. Nothing here has been verified against a live agent session.

## Framework mappings

- None declared by the selected packs.

## Limits

- "Enforced" means a Claude Code hook or permission rule acts on the agent's tool calls. It is not an operating-system sandbox and does not cover code a human runs.
- Packs are hash-pinned, not cryptographically signed.
- Advisory rules are instructions the agent may not follow.
