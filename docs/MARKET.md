# Market analysis: coding-agent guardrails (2026-09-29)

Evidence only. **[checked]** = opened and confirmed by the maintainer session on 2026-09-29. **[research]** = opened
by the research agent on the same date and not re-checked; confirm before quoting publicly. Star counts are as shown
on the page that day. No prices are stated unless a source showed one. BACKGROUND.md figures are superseded here.

## 1. The uncomfortable part: the platform already does a lot

Claude Code **auto mode** is the built-in starting mode for interactive terminal and VS Code sessions from v2.1.283
**[checked]** (https://code.claude.com/docs/en/permission-modes). Its classifier blocks by default: `curl | bash`,
production deploys and migrations, force push, irreversibly destroying pre-existing files, `git reset --hard` /
`git checkout -- .` / `git restore .`, and sending sensitive data out **[checked]**. That overlaps a large part of
Governor's block list.

What it does **not** do, per the same page **[checked]**:
- It **allows** "Reading `.env` and sending credentials to their matching API" and "Installing dependencies declared
  in your lock files or manifests".
- It is a model's judgement, not a rule: "Boundaries are not stored as rules… For a hard guarantee, add a deny rule."
- On Enterprise and API accounts, classifier calls count toward token usage.
- It does not gate "done" on tests, scan files the agent writes for keys, or tell the user which protections are
  enforced versus hoped for.

Also platform-owned **[research]**: sandboxing (off by default), managed settings for organisations, official plugins
`security-guidance` (warns) and `hookify` (user-written blocking rules). Codex and Cursor now have hooks that can block
(dcg and cc-safety-net list Codex support), which undercuts Governor's "Codex is advisory only" position; re-check
the Codex docs before claiming otherwise.

## 2. Competitors

| Name | Enforce / advise / scan | Agents | Price | Source |
|---|---|---|---|---|
| Destructive Command Guard (dcg), 6.1k stars | Enforce (pre-exec); `.env`/secret reads only via opt-in packs **[checked]** | 17+ incl. Claude Code, Codex, Cursor | Free, custom license | github.com/Dicklesworthstone/destructive_command_guard |
| cc-safety-net, 1.6k stars | Enforce: destructive git/fs, `.env`/SSH/`~/.aws` reads; presets; no written-file scan, no test gate **[checked]** | 13 incl. Claude Code, Codex, Cursor | Free, MIT | github.com/kenryu42/cc-safety-net |
| Trail of Bits claude-code-config, 2.1k stars | Enforce: deny rules, hooks, Stop hook, sandbox advice; hand-copied template **[research]** | Claude Code | Free | github.com/trailofbits/claude-code-config |
| karanb192/claude-code-hooks, 527 stars | Enforce: 22 hooks incl. secrets, test-tampering; user picks a safety level **[research]** | Claude Code | Free, MIT | github.com/karanb192/claude-code-hooks |
| GitGuardian ggshield AI hook | Enforce: blocks agent actions containing secrets; needs an account/API key **[research]** | Claude Code, Cursor, Copilot, Codex | CLI MIT; service price not verified | github.com/GitGuardian/ggshield |
| Snyk claude-plugin-snyk | Enforce: Stop hook until new vulnerabilities fixed; needs account **[research]** | Claude Code | Apache-2.0; account; price not verified | github.com/snyk/claude-plugin-snyk |
| Rulebricks claude-code-guardrails, 79 stars | Enforce against a cloud policy **[research]** | Claude Code | Hook MIT; paid cloud, price not listed | github.com/rulebricks/claude-code-guardrails |
| dwarvesf/claude-guardrails, 36 stars | Enforce (deny rules); writes to `~/.claude` **[research]** | Claude Code | Free, MIT | github.com/dwarvesf/claude-guardrails |
| AhmadShayan/claude-code-guardrails, 0 stars | Enforce, aimed at founders building with AI **[research]** | Claude Code | Free, MIT | github.com/AhmadShayan/claude-code-guardrails |
| ahmed-alstaty/guardrails-plugin, 1 star | Enforce + session report + CLAUDE.md lint **[research]** | Claude Code | Free, MIT | github.com/ahmed-alstaty/guardrails-plugin |
| Vibe-coder scanners: vibe-guard, vibe-hardening, vibeward, AppGuardrail, xlogs | Scan after the fact (vibeward also has a prompt hook) **[research]** | Agent-agnostic | Free, MIT | see BACKGROUND.md links |
| Rule generators: ClaudeForge, rulesync, ai-rules-sync, Superpowers | Advise only **[research]** | Many | Free | see BACKGROUND.md links |

**Paid vs free.** Every direct competitor found is free and open source. The paid offers found are vendor services
behind a free client (GitGuardian, Snyk, Rulebricks) and enterprise products not verified here (Certiv). Nobody was
found charging for a Claude Code guardrail plugin itself. Inference: charging for the plugin is unlikely to work;
charging for a service around it might.

## 3. Where Governor stands out (each point checked against what competitors show)

1. **Rules derived from the project, not picked by the user.** Every enforcing tool above uses fixed patterns or
   presets the user chooses. Governor detects the stack and data, asks up to 7 plain questions, and derives the tier
   (SPEC I5, T1). This is the core USP for someone who does not know which preset they need.
2. **Covers what auto mode allows.** Hard blocks on reading `.env` and secret files, approval before installing
   packages (tier 3), a secret scan on every file the agent writes (including Supabase service-role keys in
   `NEXT_PUBLIC_` variables), and a Stop hook that refuses "done" on red tests. These are deterministic rules, which
   the auto-mode docs themselves recommend for a hard guarantee.
3. **Honest labelling.** Every rule is marked enforced or advisory, with a coverage table and an evidence report
   that says it is not a certificate. No competitor opened shows which of its rules are actually enforced.
4. **Stays governed.** Lint (V8) catches edited hooks, drift flags when the project's data or exposure changes, and
   a CI gate checks the same in pull requests. Competitors install and forget.
5. **Self-protection and human-only exceptions.** The agent cannot edit its own rules, record exceptions, pass
   `--human` or uninstall Governor; the user does those. Tested against 250+ attack/benign commands and 31 edge
   cases (novice users, prompt injection, jailbreak attempts), in deterministic evals, not yet in live sessions.
6. **Keyless, offline, project-scoped.** No account, API key or network call; never writes to `~/.claude`; packs are
   hash-pinned today, with offline Ed25519 signing ready but not yet switched on (no release key yet). ggshield, Snyk and Rulebricks need accounts.
7. **Plain words.** Questions, block messages ("Why / What you can do") and `/governor:status` are written for people
   who have never heard of hooks. The tools above are written for developers.

## 4. Weak spots to be honest about

- **Traction:** dcg (6.1k) and cc-safety-net (1.6k) have large head starts and support many agents; Governor
  enforces only in Claude Code.
- **Pattern breadth:** dcg lists 50+ command packs; Governor's command patterns are narrower.
- **Not yet proven:** no live-session verification. Real-repo trials so far are deterministic only (four repos,
  docs/TRIALS.md round 1), not a week of live agent work.
- **Platform risk:** each Claude Code release can absorb features (auto mode already did for deploy/force-push).
  Governor's lasting value is the parts a classifier will not give: derived tiers, hard rules, labelled coverage,
  drift and evidence.

## 5. Positioning line (draft, for review)

"Claude Code's auto mode guesses what's dangerous. Governor makes it a rule: a few plain questions about your app,
then hard blocks on secrets, installs and unfinished work, with a report that says exactly what is and isn't
enforced. Free, offline, no account."

Monetisation options (inference, not validated): free plugin; paid team setup and review of `governance.yaml` for
agencies and small teams; paid domain packs (e.g. UK GDPR, ServiceNow); a hosted evidence-report dashboard only if
teams ask for it. Validate demand before building any of them.
