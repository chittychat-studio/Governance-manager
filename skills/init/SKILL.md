---
description: Install Governor in this repo. Detects facts, asks the user the missing ones, renders permission rules, hooks and rules files, then lints them.
argument-hint: "[--with-ci] [--mcp-allow server1,server2]"
disable-model-invocation: true
---
<!-- Plugin docs: https://code.claude.com/docs/en/plugins-reference and https://code.claude.com/docs/en/skills -->
Python command: run `python3 --version`; if it fails or opens the Microsoft Store (common on Windows), use `python` instead everywhere below.

Install Governor in the current repository. Follow these steps exactly.

1. Check Python and PyYAML: run `python3 -c "import yaml"` (use `python` if `python3` is missing).
   If PyYAML is missing, ask the user before running `python3 -m pip install pyyaml`. Do not install without a yes.
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init.py" . --questions`.
   Show the user the detected facts with their evidence.
3. Ask the user each question from the output, word for word, and show its options. Ask them all in one message.
   - Do not answer any question yourself, and do not infer answers from the code, README or existing CLAUDE.md.
   - Do not ask anything that is not in the list. In particular, never ask which guardrails or controls they want.
4. Write the answers to `.claude/governor/answers.json` as a JSON object keyed by `field`
   (lists for questions marked `multiple`). Leave out fields the user skipped.
5. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init.py" . --answers .claude/governor/answers.json $ARGUMENTS`.
6. Report the output as-is: the tier, the packs, any warnings, and the status line.
   The status is "linted" at best. Never say the setup is verified; the Q-series verify is a separate, local, paid run.
7. If it refused, show the reason (it names the field or pack) and stop. Do not work around a refusal.
8. Tell the user to review `git diff` (especially `.claude/settings.json`) and commit the result.
