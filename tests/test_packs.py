"""Phase 2 tests: T0-T6, P1-P10, P2a."""
import re
import shutil

import pytest
import yaml

import packs
import select_pack
import sign_pack
import tier
from conftest import ROOT

SPEC = (ROOT / "SPEC.md").read_text(encoding="utf-8")
SPEC_IDS = set(re.findall(r"^- \*\*([A-Z]+\d+[a-z]?)\*\*", SPEC, re.M))
BASE = dict(app_type="api", stack="fastapi-postgres", agent=["claude-code"], test_cmd="python -m pytest")


def intake(classes, exposure, tenancy):
    return dict(BASE, data_classes=classes, exposure=exposure, tenancy=tenancy)


@pytest.mark.parametrize("classes,exposure,tenancy,want", [
    (["payments"], "internal", "single", 3),            # T2
    (["health"], "internal", "single", 3),              # T2
    (["pii"], "public", "single", 3),                   # T3
    (["pii"], "internal", "multi", 3),                  # T3
    (["pii"], "internal", "single", 2),                 # T4
    (["auth"], "public", "single", 2),                  # T4
    (["auth"], "internal", "single", 1),                # T5
    (["none"], "public", "multi", 1),                   # T5
    (["auth", "pii", "payments"], "public", "multi", 3),  # T0 highest wins
])
def test_tier_table(classes, exposure, tenancy, want):
    """T0-T5."""
    assert tier.compute_tier(intake(classes, exposure, tenancy))[0] == want


def test_tier_rule_ids_exist_in_spec():
    table = tier.load_tiers()
    for r in table["rules"] + [table["default"]]:
        assert r["id"] in SPEC_IDS, r["id"]


def resolved(n):
    return packs.resolve(f"tier{n}/fastapi-postgres/claude-code")[0]


def test_strict_superset():
    """P3: tier N rules strictly contain tier N-1 rules."""
    ids = [{r["id"] for r in resolved(n)} for n in (1, 2, 3)]
    assert ids[0] < ids[1] < ids[2]


@pytest.mark.parametrize("n", [1, 2, 3])
def test_every_rule_has_p2_fields(n):
    """P2, P2a."""
    for r in resolved(n):
        assert r["enforcement"] in packs.ENFORCEMENT
        assert set(r["mechanism"]) <= packs.MECHANISMS
        assert set(r["agents"]) <= packs.AGENTS and r["agents"]


@pytest.mark.parametrize("n", [1, 2, 3])
def test_every_rule_cites_a_spec_rule(n):
    """Phase 2 exit: every pack rule's SPEC id exists."""
    for r in resolved(n):
        assert r["spec"] in SPEC_IDS, r["id"]
        assert r["id"].split("-")[0] == r["spec"]


def test_base_pack_has_every_p6_item():
    """P6: env/keys/cloud creds, MCP allowlist, rm -rf, force push, prod deploy, secret scan, stop hook."""
    rules = {r["id"]: r for r in resolved(1)}
    for rid in ("P6-secret-read", "P6-mcp-allowlist", "P6-rm-rf", "P6-force-push", "P6-prod-deploy",
                "P6-secret-scan", "P6-stop-tests"):
        assert rid in rules
    deny = rules["P6-secret-read"]["deny"]
    for needle in (".env", ".pem", ".key", "id_rsa", ".aws", "gcloud", ".azure", ".kube", ".docker"):
        assert any(needle in d for d in deny), needle
    assert rules["P6-rm-rf"]["deny"] and rules["P6-force-push"]["deny"]
    assert rules["P6-prod-deploy"]["ask"]


def test_p6_denies_are_layered():
    """P7: every P6 deny item has both a permission rule and a hook."""
    for r in resolved(1):
        if r["spec"] == "P6" and r.get("deny"):
            assert set(r["mechanism"]) == {"deny_rule", "hook"}, r["id"]
            assert r.get("hook"), r["id"]


def test_p8_repeat_limit_default_three():
    assert {r["id"]: r for r in resolved(1)}["P8-repeat-fail"]["hook"]["repeat_fail"] == 3


def test_hook_regexes_compile():
    for n in (1, 2, 3):
        for r in resolved(n):
            for key in ("bash_deny", "bash_ask"):
                for pat in r.get("hook", {}).get(key, []):
                    re.compile(pat)


def test_lock_is_current():
    """P4: PACKS.lock matches the pack files."""
    assert sign_pack.main(["--check"]) == 0


def test_hash_mismatch_refuses(tmp_path, monkeypatch):
    """P4: tampered pack -> refuse."""
    fake = tmp_path / "packs"
    shutil.copytree(packs.PACKS_DIR, fake)
    f = fake / "tier1/fastapi-postgres/claude-code.yaml"
    f.write_text(f.read_text() + "\n# tampered\n")
    monkeypatch.setattr(packs, "PACKS_DIR", fake)
    monkeypatch.setattr(packs, "LOCK_PATH", fake / "PACKS.lock")
    with pytest.raises(packs.PackError, match="hash mismatch"):
        packs.resolve("tier1/fastapi-postgres/claude-code")


def test_crlf_checkout_hashes_the_same(tmp_path):
    """P4: a Windows CRLF checkout pins identically."""
    src = packs.PACKS_DIR / "tier1/fastapi-postgres/claude-code.yaml"
    crlf = tmp_path / "x.yaml"
    crlf.write_bytes(src.read_bytes().replace(b"\n", b"\r\n"))
    assert packs.file_sha256(crlf) == packs.file_sha256(src)


def test_unknown_stack_gets_a_family_pack():
    """P1a (changed from P1's old refusal): every stack gets a pack by lookup, never a refusal for its stack."""
    js = select_pack.select(dict(BASE, stack="react-vite", data_classes=["none"], exposure="public", tenancy="single"), 1)
    assert js["claude-code"]["pack_id"] == "tier1/node/claude-code"
    other = select_pack.select(dict(BASE, stack="rails-mysql", data_classes=["none"], exposure="public",
                                    tenancy="single"), 1)
    assert other["claude-code"]["pack_id"] == "tier1/generic/claude-code"
    with pytest.raises(packs.PackError, match="no pack"):
        packs.resolve("tier1/does-not-exist/claude-code")


def test_selection_is_lookup():
    sel = select_pack.select(intake(["pii"], "public", "multi"), 3)
    assert sel["claude-code"]["pack_id"] == "tier3/fastapi-postgres/claude-code"
    assert [p for p, _ in sel["claude-code"]["pins"]] == [
        "tier1/generic/claude-code", "tier2/generic/claude-code", "tier3/generic/claude-code",
        "tier3/fastapi-postgres/claude-code"]  # P1a: the family pack extends the generic chain


def test_select_script_is_not_named_select():
    """Guard: scripts/select.py would shadow the stdlib select module."""
    assert not (ROOT / "scripts" / "select.py").exists()
