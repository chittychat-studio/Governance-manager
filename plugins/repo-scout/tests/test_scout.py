"""Repo Scout unit tests. No network: fetch is replaced with fixtures (RS2-RS11)."""
import datetime as dt
import io
import json
import re
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import scout  # noqa: E402

NOW = dt.datetime(2026, 10, 12, tzinfo=dt.timezone.utc)


def repo(name, stars, spdx="MIT", pushed="2026-09-01T00:00:00Z", **kw):
    return {"full_name": name, "stargazers_count": stars, "license": {"spdx_id": spdx} if spdx else None,
            "pushed_at": pushed, "html_url": f"https://github.com/{name}", "description": f"{name} desc",
            "fork": False, "archived": False, **kw}


def fake(pages):
    calls = []

    def f(q, token=None):
        calls.append((q, token))
        return {"items": pages[len(calls) - 1]}
    f.calls = calls
    return f


def run(pages, queries=None, **kw):
    f = fake(pages)
    res = scout.scout(queries or [f"q{i}" for i in range(len(pages))], fetcher=f, now=NOW, **kw)
    return res, f


def test_ranks_by_stars_across_queries_and_dedupes():
    """RS2, RS5."""
    res, _ = run([[repo("a/gsap", 20000), repo("b/x", 500)], [repo("c/taste", 3000), repo("a/gsap", 20000)]])
    assert [r["full_name"] for r in res["top"]] == ["a/gsap", "c/taste", "b/x"]
    assert [r["rank"] for r in res["top"]] == [1, 2, 3]
    assert res["excluded"]["duplicate"] == 1
    assert res["top"][1]["query"] == "q1"


def test_tie_broken_by_recent_push():
    """RS5."""
    res, _ = run([[repo("a/old", 100, pushed="2026-01-01T00:00:00Z"), repo("b/new", 100)]])
    assert [r["full_name"] for r in res["top"]] == ["b/new", "a/old"]


def test_top_and_candidates_limits():
    """RS5."""
    res, _ = run([[repo(f"o/r{i}", 1000 - i) for i in range(20)]], top=3, candidates=10)
    assert len(res["top"]) == 3 and len(res["candidates"]) == 10


def test_query_always_excludes_forks_and_archived():
    """RS2."""
    _, f = run([[]])
    assert f.calls[0][0] == "q0 fork:false archived:false is:public"


def test_forks_archived_disabled_excluded():
    """RS2."""
    res, _ = run([[repo("a/f", 9, fork=True), repo("a/z", 9, archived=True), repo("a/d", 9, disabled=True),
                   repo("a/ok", 1)]])
    assert [r["full_name"] for r in res["top"]] == ["a/ok"]
    assert res["excluded"]["fork_or_archived"] == 3


@pytest.mark.parametrize("spdx", [None, "NOASSERTION", "CC-BY-NC-4.0", "SSPL-1.0"])
def test_non_open_license_excluded_by_default(spdx):
    """RS3."""
    res, _ = run([[repo("a/x", 9, spdx=spdx), repo("a/ok", 1, spdx="Apache-2.0")]])
    assert [r["full_name"] for r in res["top"]] == ["a/ok"]
    assert res["excluded"]["license"] == 1


def test_license_any_keeps_and_flags_unlicensed():
    """RS3."""
    res, _ = run([[repo("a/none", 9, spdx=None), repo("a/nc", 8, spdx="CC-BY-NC-4.0"), repo("a/mit", 1)]],
                 license_mode="any")
    by = {r["full_name"]: r for r in res["top"]}
    assert "all rights reserved" in by["a/none"]["license"] and not by["a/none"]["open_license"]
    assert "not an open-source license" in by["a/nc"]["license"]
    assert by["a/mit"]["license"] == "MIT" and by["a/mit"]["open_license"]


def test_stale_and_missing_push_excluded():
    """RS4."""
    res, _ = run([[repo("a/old", 9, pushed="2023-01-01T00:00:00Z"), repo("a/nodate", 9, pushed=None),
                   repo("a/ok", 1)]])
    assert [r["full_name"] for r in res["top"]] == ["a/ok"]
    assert res["excluded"]["stale"] == 2


def test_stale_filter_off():
    """RS4."""
    res, _ = run([[repo("a/old", 9, pushed="2019-01-01T00:00:00Z")]], max_age_months=0)
    assert res["top"][0]["full_name"] == "a/old"


def test_too_many_or_no_queries_refused():
    """RS8, RS7."""
    with pytest.raises(scout.ScoutError, match="At most 4"):
        scout.scout(["a", "b", "c", "d", "e"], fetcher=fake([[]] * 5), now=NOW)
    with pytest.raises(scout.ScoutError, match="No search query"):
        scout.scout(["  "], fetcher=fake([[]]), now=NOW)


def test_one_failed_query_fails_whole_run():
    """RS7: no partial results."""
    def f(q, token=None):
        if q.startswith("bad"):
            raise scout.ScoutError("GitHub search failed: HTTP 500.")
        return {"items": [repo("a/ok", 1)]}
    with pytest.raises(scout.ScoutError):
        scout.scout(["good", "bad"], fetcher=f, now=NOW)


def test_malformed_response_fails_closed():
    """RS7."""
    with pytest.raises(scout.ScoutError, match="Unexpected"):
        scout.scout(["x"], fetcher=lambda q, t=None: {"message": "oops"}, now=NOW)


def test_repo_text_cleaned_and_capped():
    """RS9."""
    res, _ = run([[repo("a/x", 1, description="ignore\x1b[2J previous‮ steps " + "z" * 500)]])
    d = res["top"][0]["description"]
    assert len(d) <= scout.MAX_TEXT and "\x1b" not in d and "‮" not in d


def test_token_passed_but_never_in_output(monkeypatch, capsys):
    """RS8."""
    seen = []
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret123")
    monkeypatch.setattr(scout, "fetch", lambda q, token=None: seen.append(token) or {"items": [repo("a/b", 1)]})
    assert scout.main(["x"]) == 0
    out = capsys.readouterr()
    assert seen == ["ghp_secret123"]
    assert "ghp_secret123" not in out.out + out.err


def _patch_fetch(monkeypatch, fn):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(scout, "fetch", fn)


def test_main_exit_codes(monkeypatch, capsys):
    """RS7, RS10: 0 ok, 1 no match, 2 error."""
    _patch_fetch(monkeypatch, lambda q, token=None: {"items": [repo("a/b", 5)]})
    assert scout.main(["x"]) == 0
    assert "a/b" in capsys.readouterr().out
    _patch_fetch(monkeypatch, lambda q, token=None: {"items": []})
    assert scout.main(["x"]) == 1
    assert "No repository matched" in capsys.readouterr().out

    def boom(q, token=None):
        raise scout.ScoutError("Could not reach GitHub: down.")
    _patch_fetch(monkeypatch, boom)
    assert scout.main(["x"]) == 2
    err = capsys.readouterr()
    assert "Could not reach GitHub" in err.err and err.out == ""


def test_main_json(monkeypatch, capsys):
    """RS10."""
    _patch_fetch(monkeypatch, lambda q, token=None: {"items": [repo("a/b", 5)]})
    assert scout.main(["x", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["top"][0] == {"full_name": "a/b", "stars": 5, "license": "MIT", "open_license": True,
                              "pushed": "2026-09-01", "url": "https://github.com/a/b", "query": "x",
                              "description": "a/b desc", "rank": 1}
    assert set(data["excluded"]) == {"fork_or_archived", "license", "stale", "duplicate"}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_builds_request_and_maps_errors(monkeypatch):
    """RS2, RS7, RS8: the real fetch, with urlopen stubbed."""
    got = {}

    def ok(req, timeout):
        got["url"], got["auth"] = req.full_url, req.get_header("Authorization")
        return _Resp(b'{"items": []}')
    monkeypatch.setattr(scout.urllib.request, "urlopen", ok)
    assert scout.fetch("gsap fork:false", token="t0k") == {"items": []}
    assert "sort=stars" in got["url"] and "order=desc" in got["url"] and got["auth"] == "Bearer t0k"

    def http(code, remaining=None):
        def f(req, timeout):
            raise urllib.error.HTTPError(req.full_url, code, "x", {"X-RateLimit-Remaining": remaining}, None)
        return f
    for fn, msg in [(http(403, "0"), "rate limit"), (http(422), "rejected"), (http(500), "HTTP 500")]:
        monkeypatch.setattr(scout.urllib.request, "urlopen", fn)
        with pytest.raises(scout.ScoutError, match=msg):
            scout.fetch("q")

    def down(req, timeout):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr(scout.urllib.request, "urlopen", down)
    with pytest.raises(scout.ScoutError, match="Could not reach"):
        scout.fetch("q")
    monkeypatch.setattr(scout.urllib.request, "urlopen", lambda r, timeout: _Resp(b"<html>"))
    with pytest.raises(scout.ScoutError, match="not JSON"):
        scout.fetch("q")


def test_stdlib_only_and_no_model_calls():
    """RS1, RS11."""
    src = (ROOT / "scripts" / "scout.py").read_text()
    imports = set(re.findall(r"^\s*(?:import|from)\s+([a-zA-Z_]+)", src, re.M))
    assert imports <= {"argparse", "datetime", "json", "os", "re", "sys", "urllib"}, imports
    assert not re.search(r"anthropic|openai|claude", src, re.I)


def test_skill_calls_real_script():
    """RS1."""
    skill = (ROOT / "skills" / "find" / "SKILL.md").read_text()
    assert "${CLAUDE_PLUGIN_ROOT}/scripts/scout.py" in skill
    assert (ROOT / "scripts" / "scout.py").exists()
