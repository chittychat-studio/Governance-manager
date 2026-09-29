---
description: Record a Governor exception (disable one rule, or lower the tier) with a written reason. Exceptions are made by a human, not the agent.
argument-hint: "--rule <RULE-ID> | --tier <N>  --reason \"at least 20 characters\""
disable-model-invocation: true
---
Python command: run `python3 --version`; if it fails or opens the Microsoft Store (common on Windows), use `python` instead everywhere below.

The user wants an exception: $ARGUMENTS

Exceptions weaken guardrails, so a human records them (SPEC X1). Governor's hook blocks the agent from running
`exceptions.py`, so do not try, and do not look for a way around it.

1. If the user did not give a reason of at least 20 characters, ask for one. Never write the reason yourself.
2. Give the user this exact command to run in their own terminal (outside Claude Code), filled in with their
   rule or tier and reason:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/exceptions.py" . --rule <RULE-ID> --reason "<their reason>"`
   (or `--tier <N>` instead of `--rule`). It records the date and `git config user.email`, and refuses unknown
   rules, short reasons and tier raises.
3. When the user says it is done, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render.py" .` and then
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lint.py" .`, and report what was disabled or lowered and the lint result.
