---
description: Read-only audit of this repo's existing agent config (CLAUDE.md, AGENTS.md, settings, hooks) against the tier its facts imply. Lists missing rules by ID.
---
Python command: run `python3 --version`; if it fails or opens the Microsoft Store (common on Windows), use `python` instead everywhere below.

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py" .` and report the output as printed.

- Make no changes. Doctor is read-only.
- Point out every "assumed" line: those facts were unknown, and the worst case was used.
- If the user wants the gaps fixed, suggest `/governor:init`.
