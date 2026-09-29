---
description: Record a Governor exception (disable one rule, or lower the tier) with a written reason, then re-render and lint.
argument-hint: "--rule <RULE-ID> | --tier <N>  --reason \"at least 20 characters\""
disable-model-invocation: true
---
Python command: run `python3 --version`; if it fails or opens the Microsoft Store (common on Windows), use `python` instead everywhere below.

Record an exception exactly as the user asked: $ARGUMENTS

1. If the user did not give a reason of at least 20 characters, ask for one. Never write the reason yourself.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/exceptions.py" . $ARGUMENTS`.
   It records the date and `git config user.email`, and refuses unknown rules, short reasons and tier raises.
3. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render.py" .` then `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lint.py" .`
4. Report what was disabled or lowered, and the lint result. If anything refused, show the message and stop.
