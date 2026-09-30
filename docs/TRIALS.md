# Real-repo trials (SPEC T3 [G], EV4)

Goal: three real projects, ideally one FastAPI + Postgres (DeckForge), one Next.js/React (with Supabase or Firebase)
and one other, used for normal work for at least a week each. What we learn: does the tier table put each repo in
the right place, and how often does Governor get in the way of legitimate work?

## Per repo

1. New branch, `/governor:init`, commit, restart Claude Code.
2. Note: detected facts (right or wrong?), questions asked, tier, anything confusing.
3. Work normally. When Governor blocks or asks, note in the log below whether it was **right** (it stopped something
   you did not want), **friction** (you wanted it and had to work around it) or **unsure**.
4. After a week: `python scripts/friction.py . --days 7` and `/governor:status`, and fill in the summary.

## Log

| Date | Repo | Rule | What the agent tried | Right / friction / unsure | Note |
|---|---|---|---|---|---|

## Summary per repo

| Repo | Stack / family | Tier (right?) | Blocks | Asks | Friction count | Would you keep it on? |
|---|---|---|---|---|---|---|

Pass bar for a public "works on real projects" claim: three repos done, tier judged right on all three, and no rule
whose friction count exceeds its "right" count without a change or an exception reason recorded. Until then, say
"tested on the reference fixture and eval corpora only".
