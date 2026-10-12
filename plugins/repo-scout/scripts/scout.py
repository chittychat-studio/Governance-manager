#!/usr/bin/env python3
"""Find the most-starred open-source GitHub repos matching search queries (SPEC RS1-RS11).

Usage: scout.py "query one" ["query two" ...] [--top 3] [--candidates 10]
                [--license open|any] [--max-age-months 24] [--json]
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com/search/repositories"
MAX_QUERIES = 4  # RS8: unauthenticated search limit is 10 requests a minute
MAX_TEXT = 200  # RS9

# RS3: OSI-approved licenses GitHub commonly detects.
OPEN_LICENSES = {
    "0BSD", "AFL-3.0", "AGPL-3.0", "Apache-2.0", "Artistic-2.0", "BSD-2-Clause", "BSD-3-Clause",
    "BSD-3-Clause-Clear", "BSL-1.0", "CC0-1.0", "ECL-2.0", "EPL-1.0", "EPL-2.0", "EUPL-1.1",
    "EUPL-1.2", "GPL-2.0", "GPL-3.0", "ISC", "LGPL-2.1", "LGPL-3.0", "MIT", "MIT-0", "MPL-2.0",
    "MS-PL", "MS-RL", "NCSA", "OFL-1.1", "OSL-3.0", "PostgreSQL", "Unlicense", "UPL-1.0", "Zlib",
}

_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")


class ScoutError(Exception):
    """RS7: any failure that must end the run."""


def clean(text):
    """RS9: strip control/bidi characters and cap length."""
    text = _CTRL.sub(" ", text or "").strip()
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def build_query(q):
    """RS2: always exclude forks and archived repos."""
    return f"{q.strip()} fork:false archived:false is:public"


def fetch(query, token=None, timeout=20):
    """RS2, RS7, RS8: one search request; raises ScoutError on any failure."""
    params = urllib.parse.urlencode({"q": query, "sort": "stars", "order": "desc", "per_page": 30})
    req = urllib.request.Request(f"{API}?{params}", headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "repo-scout",
    })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429) and e.headers.get("X-RateLimit-Remaining") == "0":
            raise ScoutError("GitHub rate limit reached. Wait a minute, or set GITHUB_TOKEN, then retry.") from None
        if e.code == 422:
            raise ScoutError(f"GitHub rejected the query {query!r} (HTTP 422). Simplify it.") from None
        raise ScoutError(f"GitHub search failed: HTTP {e.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ScoutError(f"Could not reach GitHub: {getattr(e, 'reason', e)}.") from None
    except json.JSONDecodeError:
        raise ScoutError("GitHub returned a response that is not JSON.") from None


def _pushed(item):
    try:
        return dt.datetime.fromisoformat(item["pushed_at"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, ValueError):
        return None


def scout(queries, fetcher=fetch, top=3, candidates=10, license_mode="open", max_age_months=24,
          now=None, token=None):
    """RS2-RS5: search, merge, filter, rank. Returns a result dict; raises ScoutError (RS7)."""
    queries = [q.strip() for q in queries if q and q.strip()]
    if not queries:
        raise ScoutError("No search query given.")
    if len(queries) > MAX_QUERIES:
        raise ScoutError(f"At most {MAX_QUERIES} queries per run (GitHub rate limit); got {len(queries)}.")
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=30.44 * max_age_months) if max_age_months > 0 else None

    excluded = {"fork_or_archived": 0, "license": 0, "stale": 0, "duplicate": 0}
    seen, kept = set(), []
    for q in queries:
        data = fetcher(build_query(q), token)
        items = data.get("items")
        if not isinstance(items, list):
            raise ScoutError(f"Unexpected GitHub response for {q!r}.")
        for it in items:
            name = it.get("full_name")
            if not name:
                continue
            if name in seen:
                excluded["duplicate"] += 1
                continue
            seen.add(name)
            if it.get("fork") or it.get("archived") or it.get("disabled"):
                excluded["fork_or_archived"] += 1
                continue
            spdx = (it.get("license") or {}).get("spdx_id")
            is_open = spdx in OPEN_LICENSES
            if license_mode == "open" and not is_open:
                excluded["license"] += 1
                continue
            pushed = _pushed(it)
            if cutoff and (pushed is None or pushed < cutoff):
                excluded["stale"] += 1
                continue
            if is_open:
                label = spdx
            elif not spdx or spdx == "NOASSERTION":
                label = "none (no license: all rights reserved by default)"
            else:
                label = f"{spdx} (not an open-source license)"
            kept.append({
                "full_name": clean(name),
                "stars": int(it.get("stargazers_count") or 0),
                "license": label,
                "open_license": is_open,
                "pushed": pushed.date().isoformat() if pushed else "unknown",
                "_pushed": pushed.timestamp() if pushed else 0.0,
                "url": clean(it.get("html_url") or f"https://github.com/{name}"),
                "query": q,
                "description": clean(it.get("description")),
            })

    kept.sort(key=lambda r: (-r["stars"], -r["_pushed"], r["full_name"]))  # RS5
    for i, r in enumerate(kept, 1):
        r["rank"] = i
        del r["_pushed"]
    return {
        "queries": queries,
        "license_mode": license_mode,
        "max_age_months": max_age_months,
        "excluded": excluded,
        "top": kept[:top],
        "candidates": kept[:max(candidates, top)],
    }


def render(result):
    """RS10: plain table for people."""
    out = [f"Queries: {'; '.join(result['queries'])}",
           f"Filters: license={result['license_mode']}, last push within "
           f"{result['max_age_months'] or 'any'} months, no forks, no archived",
           "Excluded: " + ", ".join(f"{k}={v}" for k, v in result["excluded"].items()), ""]
    if not result["candidates"]:
        out.append("No repository matched after filtering.")
        return "\n".join(out)
    out.append("Shortlist (stars, descending):")
    for r in result["candidates"]:
        out.append(f"{r['rank']:>2}. {r['full_name']}  ★{r['stars']:,}  {r['license']}  pushed {r['pushed']}")
        out.append(f"    {r['url']}  [query: {r['query']}]")
        if r["description"]:
            out.append(f"    {r['description']}")
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("queries", nargs="+")
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--candidates", type=int, default=10)
    p.add_argument("--license", dest="license_mode", choices=["open", "any"], default="open")
    p.add_argument("--max-age-months", type=int, default=24)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if a.top < 1 or a.candidates < 1 or a.max_age_months < 0:
        p.error("--top and --candidates must be >= 1, --max-age-months >= 0")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")  # RS8: never printed
    try:
        res = scout(a.queries, fetcher=fetch, top=a.top, candidates=a.candidates, license_mode=a.license_mode,
                    max_age_months=a.max_age_months, token=token)
    except ScoutError as e:
        print(f"repo-scout: {e}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2, ensure_ascii=False) if a.json else render(res))
    return 0 if res["candidates"] else 1


if __name__ == "__main__":
    sys.exit(main())
