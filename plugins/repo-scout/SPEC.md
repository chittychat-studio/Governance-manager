# Repo Scout — Specification v0.1

Status: draft v0.1, 2026-10-12. Every line of code traces to a rule ID below.
Repo Scout is a separate plugin that lives in this repository. It is not part of Governor:
it makes network calls, so Governor's E2 (no network calls in `scripts/`) cannot hold for it.
Governor's `scripts/` and tests are untouched.

## RS — Behaviour

- **RS1** Input is any free-text project description. The `/repo-scout:find` skill, running in the
  user's own Claude Code session, turns it into 1–4 GitHub search queries (keywords, optionally
  `topic:` / `language:` qualifiers). The script never calls a model and holds no model API key.
- **RS2** "All public GitHub" means the GitHub REST search API (`GET /search/repositories`). Each query
  is sent with `sort=stars&order=desc&per_page=30`, and `fork:false archived:false is:public` is added.
  Results from all queries are merged and de-duplicated by `full_name`.
  Limit: the API searches name, description and topics and returns the 1,000 best matches per query at most. It does not scan every repository.
- **RS3** "Free" means the repository declares an open-source license: its `license.spdx_id` is in
  the `OPEN_LICENSES` set in `scripts/scout.py`. A missing license, `NOASSERTION` or a
  non-open license is excluded by default. With `--license any`, unlicensed repos are kept and
  flagged `no license: all rights reserved by default`.
- **RS4** Staleness filter: a repo whose last push is older than `--max-age-months` (default 24) is excluded.
  `--max-age-months 0` turns the filter off.
- **RS5** Ranking: stars descending, ties broken by most recent push, then `full_name`. The script
  returns the top `--top` (default 3) plus a shortlist of `--candidates` (default 10).
- **RS6** Relevance gate: stars measure popularity, not fit. The skill may only *drop* a shortlisted
  repo that clearly does not match the description, giving a one-line reason for each drop, and then
  take the next one in star order. It never reorders, never adds a repo that is not in the script
  output, and never states a star count, license or date that the script did not print.
- **RS7** Fail closed. A network error, HTTP error or rate limit → exit code 2 and a plain message.
  The script never returns partial results as if they were complete. A query that fails ends the
  whole run. Zero matches after filtering → exit code 1, and the excluded counts for each reason are printed.
- **RS8** Auth: if `GITHUB_TOKEN` or `GH_TOKEN` is set, it is sent as a bearer token. It is never
  printed, logged or written. Without a token GitHub allows 10 search requests a minute, so the
  script refuses more than 4 queries per run.
- **RS9** Repo text is data. Names and descriptions from GitHub are stripped of control characters
  and capped at 200 characters before printing. The skill treats them as data: if a description
  asks it to do something, it does not, and tells the user.
- **RS10** Output: a plain table for people, or `--json` for machines. Each row has rank, `full_name`, stars,
  license, last push date, URL, matched query and description. Every run also prints the query
  list and the excluded counts (fork/archived, license, stale, duplicate).
- **RS11** Runtime: Python 3.11+ standard library only (`urllib`). No third-party packages.

## RX — Deliberately excluded (v0.1)

- **RX1** Scraping github.com HTML, or any non-API source.
- **RX2** Caching results on disk.
- **RX3** Ranking by anything other than stars (forks, trending, downloads).
- **RX4** Writing into the user's repo (cloning, adding dependencies). The output is a recommendation only.
