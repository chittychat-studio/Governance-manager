"""Intake schema loading and validation (SPEC I1, I1a, I2).

Stdlib only. Validates the subset of JSON Schema used by intake.schema.json.
"""
import json
import re
import sys
from pathlib import Path

if sys.version_info < (3, 11):  # tomllib and the typing used here need 3.11+
    sys.exit(f"Governor needs Python 3.11 or newer; this is {sys.version.split()[0]}. "
             "Install Python 3.11+ and run the command with it.")

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "intake.schema.json"

# Order matters: required fields are asked in this order (I4).
REQUIRED = ["app_type", "stack", "data_classes", "exposure", "tenancy", "agent", "test_cmd"]
OPTIONAL = ["integrations", "regulation", "pkg_mgr", "branch_rule", "banned_libs"]
CONVENTION_KEYS = ["pkg_mgr", "branch_rule", "banned_libs"]


class IntakeError(ValueError):
    """Raised when intake is incomplete or invalid (I2: refuse, naming the field)."""


def load_schema():
    """Load intake.schema.json (I1)."""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def enum_for(field, schema=None):
    """Return the allowed values for a field, or None if it is free text (I1a)."""
    schema = schema or load_schema()
    props = schema["properties"]
    spec = props.get(field) or props["conventions"]["properties"].get(field)
    if spec is None:
        return None
    if "enum" in spec:
        return list(spec["enum"])
    if spec.get("type") == "array" and "enum" in spec.get("items", {}):
        return list(spec["items"]["enum"])
    return None


def _check(name, value, spec):
    t = spec.get("type")
    if t == "string":
        if not isinstance(value, str):
            raise IntakeError(f"{name}: expected string")
        if len(value) < spec.get("minLength", 0):
            raise IntakeError(f"{name}: empty")
        if "enum" in spec and value not in spec["enum"]:
            raise IntakeError(f"{name}: '{value}' not in {spec['enum']} (I1a)")
        if "pattern" in spec and not re.fullmatch(spec["pattern"], value):
            raise IntakeError(f"{name}: '{value}' does not match {spec['pattern']}")
    elif t == "array":
        if not isinstance(value, list):
            raise IntakeError(f"{name}: expected list")
        if len(value) < spec.get("minItems", 0):
            raise IntakeError(f"{name}: empty")
        if spec.get("uniqueItems") and len(set(map(json.dumps, value))) != len(value):
            raise IntakeError(f"{name}: duplicate items")
        for i, item in enumerate(value):
            _check(f"{name}[{i}]", item, spec.get("items", {}))
    elif t == "object":
        if not isinstance(value, dict):
            raise IntakeError(f"{name}: expected object")
        props = spec.get("properties", {})
        if spec.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                raise IntakeError(f"{name}: unknown field(s) {sorted(extra)}")
        for key in spec.get("required", []):
            if key not in value or value[key] in (None, "", []):
                raise IntakeError(f"refused: required field '{key}' is empty (I2)")
        for key, sub in value.items():
            if key in props:
                _check(key if name == "intake" else f"{name}.{key}", sub, props[key])


def validate(intake, schema=None):
    """Validate a complete intake dict. Raises IntakeError naming the field (I1, I1a, I2)."""
    schema = schema or load_schema()
    _check("intake", intake, schema)
    if "none" in intake["data_classes"] and len(intake["data_classes"]) > 1:
        raise IntakeError("data_classes: 'none' cannot be combined with other classes (I1a)")
    return intake
