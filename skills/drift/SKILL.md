---
description: Check whether this repo has drifted from its installed Governor setup (new data classes, exposure or tenancy change, tier increase, stale files).
---
Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/drift.py" .` and report each DRIFT and warning line as printed.

If drift is found, tell the user to re-run `/governor:init` to re-answer the changed facts and re-render.
Do not edit governance.yaml or the rendered files by hand.
