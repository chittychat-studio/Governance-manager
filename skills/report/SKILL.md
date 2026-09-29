---
description: Write Governor's one-page evidence report for this repo (tier, enforced vs advisory counts, exceptions, lint, drift, last verify status).
disable-model-invocation: true
---
Python command: run `python3 --version`; if it fails or opens the Microsoft Store (common on Windows), use `python` instead everywhere below.

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/report.py" . --out governor-report.md` and show the file.

Do not add claims, figures or framework mappings that are not in the generated report.
The report is not a compliance certificate, and it says so.
