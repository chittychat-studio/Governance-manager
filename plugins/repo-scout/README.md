# Repo Scout

Describe your project in plain words. Get the 3 most-starred open-source GitHub repos that fit it.

```
/repo-scout:find a portfolio website with smooth scroll animations and good design taste
```

How it works (rules in `SPEC.md`):
1. The skill turns your description into 1–4 GitHub search queries (RS1).
2. `scripts/scout.py` runs them against the GitHub search API, sorted by stars, no forks, no archived repos (RS2).
3. It keeps only repos with an open-source license (RS3) that were pushed in the last 24 months (RS4), then ranks by stars (RS5).
4. The skill can drop off-topic repos from the shortlist, giving a reason, but it never reorders the list or adds repos (RS6).

Limits: this is GitHub search, not a scan of every repository. Stars measure popularity, not quality.
Repos with no license file are excluded by default (`--license any` keeps them, flagged).

Optional: set `GITHUB_TOKEN` to raise GitHub's rate limit. It is never printed.

Direct use: `python3 scripts/scout.py "animation library" "topic:css-framework" [--json] [--license any] [--max-age-months 12]`

Tests: `python3 -m pytest plugins/repo-scout/tests`
