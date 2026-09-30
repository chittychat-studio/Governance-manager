"""miniyaml must read every YAML file Governor ships exactly as PyYAML does, and round-trip (SPEC E8)."""
import datetime
import subprocess
import sys

import pytest
import yaml

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import miniyaml  # noqa: E402

# Files outside the subset on purpose: block scalars (GitHub workflow `run: |`) and anchors/merge keys (eval corpus).
OUTSIDE_SUBSET = {".github/workflows/compat.yml", ".github/workflows/ci.yml", "templates/github/governor.yml",
                  "evals/edge.yaml", "evals/detection.yaml"}  # detection.yaml: !!binary test bytes (dev only)
FILES = [f for f in subprocess.run(["git", "ls-files", "*.yaml", "*.yml"], cwd=ROOT, capture_output=True,
                                   text=True).stdout.split() if f not in OUTSIDE_SUBSET]


@pytest.mark.parametrize("rel", FILES)
def test_load_matches_pyyaml(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert miniyaml.load(text) == yaml.safe_load(text)


def test_runtime_files_are_covered():
    """Every file the user path reads is in FILES (packs, tiers)."""
    assert "tiers.yaml" in FILES
    assert any(f.startswith("packs/tier1/generic/") for f in FILES)


SAMPLES = [
    {"a": 1, "b": [1, 2, {"c": None, "d": [True, False]}], "e": {}, "f": [], "g": "x: y", "h": "#not a comment"},
    {"text": "It's a 'quoted' \"string\" with \\ backslash and unicode é ✓", "n": -3, "f": 1.5,
     "date": datetime.date(2026, 9, 29), "s_date": "2026-09-29", "yes": "yes", "null_str": "null", "empty": ""},
    {"long": "word " * 60, "nested": [[1, 2], [3, [4, 5]]], "multi": "line1\nline2\n\nline4",
     "regex": r"(?<![\w.-])\.env(\.[\w-]+)?(?![\w.-])", "colon_end": "ends with:", "lead_space": "  x"},
    [{"id": "P6-rm-rf", "deny": ["Bash(rm -rf *)"], "hook": {"bash_deny": ["^rm\\s+-rf"]}}],
]


@pytest.mark.parametrize("obj", SAMPLES)
def test_dump_round_trips_through_both(obj):
    text = miniyaml.dump(obj)
    assert yaml.safe_load(text) == obj
    assert miniyaml.load(text) == obj


@pytest.mark.parametrize("obj", SAMPLES)
def test_reads_pyyaml_output(obj):
    """Existing governance.yaml files were written by yaml.safe_dump, which folds long lines."""
    for kw in ({}, {"default_flow_style": True}, {"width": 30}, {"allow_unicode": True}):
        assert miniyaml.load(yaml.safe_dump(obj, sort_keys=False, **kw)) == obj


def test_reads_real_governance_files(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import governance
    gov = governance.build({"app_type": "api", "stack": "fastapi-postgres", "data_classes": ["pii"],
                            "exposure": "public", "tenancy": "single", "agent": ["claude-code", "codex"],
                            "test_cmd": "python -m pytest"})
    gov["exceptions"] = [{"kind": "rule", "rule": "P8-paid-cli", "reason": "long reason " * 12,
                          "date": "2026-09-29", "by": "a@b.c"}]
    assert miniyaml.load(yaml.safe_dump(gov, sort_keys=False)) == gov
    assert yaml.safe_load(miniyaml.dump(gov)) == gov


@pytest.mark.parametrize("bad", ["a: &x 1\nb: *x\n", "a: |\n  text\n", "a: 1\n---\nb: 2\n", "a: !!str 1\n",
                                 "a: [1, 2\n", 'a: "open\n', "a: 1\na: 2\n", "? x\n: 1\n"])
def test_refuses_outside_subset(bad):
    with pytest.raises(miniyaml.YamlError):
        miniyaml.load(bad)
