"""Detect intake facts from a repository without asking anything (SPEC I3, E2).

Deterministic, stdlib only, no network. Every detected value carries evidence
(the file and the reason). A field is only filled when there is positive
evidence; absence of evidence leaves it in `unknown[]` (fail closed).

Usage: python scripts/detect.py <repo_dir> [--out detected.json]
"""
import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from intake import OPTIONAL, REQUIRED  # noqa: E402

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build",
             ".next", ".mypy_cache", ".pytest_cache", "site-packages", ".tox"}
SOURCE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".sql", ".prisma", ".mjs", ".cjs"}
MAX_FILE_BYTES = 200_000
MAX_FILES = 3000

PY_DB = {"psycopg", "psycopg2", "psycopg2-binary", "asyncpg", "psycopg-binary"}
NODE_DB = {"pg", "postgres", "pg-promise"}
AUTH_LIBS = {"passlib", "python-jose", "pyjwt", "fastapi-users", "bcrypt", "authlib", "argon2-cffi",
             "jsonwebtoken", "passport", "bcryptjs", "next-auth", "express-session", "@auth/core"}
PAYMENT_LIBS = {"stripe", "@stripe/stripe-js", "braintree", "paypalrestsdk", "@paypal/checkout-server-sdk"}
HEALTH_LIBS = {"fhir.resources", "fhirclient", "hl7", "hl7apy", "fhir-kit-client"}
INTEGRATION_LIBS = {"stripe": "stripe", "@stripe/stripe-js": "stripe", "supabase": "supabase",
                    "@supabase/supabase-js": "supabase", "openai": "openai", "anthropic": "anthropic",
                    "@anthropic-ai/sdk": "anthropic", "sendgrid": "sendgrid", "@sendgrid/mail": "sendgrid",
                    "twilio": "twilio", "boto3": "aws", "@aws-sdk/client-s3": "aws"}
PUBLIC_DEPLOY_FILES = ["vercel.json", "netlify.toml", "fly.toml", "render.yaml", "railway.json",
                       "app.yaml", "Procfile"]
PII_RE = re.compile(r"\b(email|phone|phone_number|date_of_birth|dob|home_address|postcode|zip_code|ssn|"
                    r"national_insurance(?:_number)?|first_name|last_name|full_name)\b"
                    r"(?:\s*[:=(]|\s+(?:text|varchar|char|citext|date)\b)", re.I)
TENANT_RE = re.compile(r"\b(tenant_id|organization_id|org_id|workspace_id)\b", re.I)
NPM_DEFAULT_TEST = 'echo "Error: no test specified" && exit 1'


def _norm(name):
    """Normalise a Python requirement string to its package name (I3)."""
    return re.split(r"[\s<>=!~\[;]", name.strip().lower(), maxsplit=1)[0]


def read_python_deps(repo):
    """Collect Python dependency names with their source file (I3)."""
    deps = {}
    for req in sorted(repo.glob("requirements*.txt")):
        for line in req.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not line.startswith("-"):
                deps.setdefault(_norm(line), req.name)
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            data = {}
        names = list(data.get("project", {}).get("dependencies", []))
        for group in data.get("project", {}).get("optional-dependencies", {}).values():
            names.extend(group)
        names.extend(data.get("tool", {}).get("poetry", {}).get("dependencies", {}).keys())
        for n in names:
            deps.setdefault(_norm(n), "pyproject.toml")
    return deps


def read_package_json(repo):
    """Return (deps {name: 'package.json'}, scripts dict) (I3)."""
    pkg = repo / "package.json"
    if not pkg.exists():
        return {}, {}
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}, {}
    deps = {}
    for key in ("dependencies", "devDependencies"):
        for n in data.get(key, {}) or {}:
            deps[n.lower()] = "package.json"
    return deps, data.get("scripts", {}) or {}


def iter_source_files(repo):
    """Yield source files, skipping vendored/build dirs, bounded (I3)."""
    count = 0
    for path in sorted(repo.rglob("*")):
        if any(part in SKIP_DIRS for part in path.relative_to(repo).parts):
            continue
        if path.is_file() and path.suffix in SOURCE_EXT and path.stat().st_size <= MAX_FILE_BYTES:
            count += 1
            if count > MAX_FILES:
                return
            yield path


def detect(repo_dir):
    """Detect intake fields from repo facts. Returns {detected, evidence, unknown} (I3)."""
    repo = Path(repo_dir).resolve()
    if not repo.is_dir():
        raise FileNotFoundError(f"not a directory: {repo}")
    detected, evidence = {}, {}

    def put(field, value, why):
        detected[field] = value
        evidence.setdefault(field, []).append(why)

    py = read_python_deps(repo)
    node, scripts = read_package_json(repo)
    alldeps = {**py, **node}

    # stack + app_type
    framework = app_type = None
    for name, fw, at in (("fastapi", "fastapi", "api"), ("django", "django", "fullstack"),
                         ("flask", "flask", "api"), ("next", "next", "fullstack"),
                         ("express", "node-express", "api")):
        if name in alldeps:
            framework, app_type = fw, at
            src = alldeps[name]
            break
    if framework is None and "react" in node and "vite" in node:
        framework, app_type, src = "react-vite", "web-spa", "package.json"
    if framework:
        db = None
        if PY_DB & set(py) or NODE_DB & set(node):
            db = "postgres"
            dbsrc = sorted((PY_DB & set(py)) | (NODE_DB & set(node)))
        put("stack", f"{framework}-{db}" if db else framework,
            f"{src}: {framework} dependency" + (f"; postgres driver {dbsrc}" if db else ""))
        put("app_type", app_type, f"{src}: {framework} implies {app_type}")

    # data_classes (only positive evidence; never infer 'none')
    classes = []
    for cls, libs in (("auth", AUTH_LIBS), ("payments", PAYMENT_LIBS), ("health", HEALTH_LIBS)):
        hits = sorted(libs & set(alldeps))
        if hits:
            classes.append(cls)
            evidence.setdefault("data_classes", []).append(f"{alldeps[hits[0]]}: {cls} library {hits}")
    pii_file = tenant_file = None
    for f in iter_source_files(repo):
        text = f.read_text(encoding="utf-8", errors="ignore")
        if pii_file is None and PII_RE.search(text):
            pii_file = f
            m = PII_RE.search(text)
        if tenant_file is None and TENANT_RE.search(text):
            tenant_file = f
            t = TENANT_RE.search(text)
        if pii_file and tenant_file:
            break
    if pii_file:
        classes.append("pii")
        evidence.setdefault("data_classes", []).append(
            f"{pii_file.relative_to(repo).as_posix()}: personal-data field '{m.group(1)}'")
    if classes:
        detected["data_classes"] = sorted(set(classes))

    # exposure: only 'public' is detectable (a public hosting config)
    for name in PUBLIC_DEPLOY_FILES:
        if (repo / name).exists():
            put("exposure", "public", f"{name}: public hosting config")
            break

    # tenancy: only 'multi' is detectable
    if tenant_file:
        put("tenancy", "multi", f"{tenant_file.relative_to(repo).as_posix()}: tenant key '{t.group(1)}'")

    # agent
    agents = []
    if (repo / "CLAUDE.md").exists() or (repo / ".claude").is_dir():
        agents.append("claude-code")
        evidence.setdefault("agent", []).append("CLAUDE.md or .claude/ present")
    if (repo / "AGENTS.md").exists() or (repo / ".codex").is_dir():
        agents.append("codex")
        evidence.setdefault("agent", []).append("AGENTS.md or .codex/ present")
    if agents:
        detected["agent"] = agents

    # conventions.pkg_mgr
    for lock, mgr in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("package-lock.json", "npm"),
                      ("uv.lock", "uv"), ("poetry.lock", "poetry")):
        if (repo / lock).exists():
            put("pkg_mgr", mgr, f"{lock} present")
            break
    else:
        if py and any(repo.glob("requirements*.txt")):
            put("pkg_mgr", "pip", "requirements*.txt present")
        elif node:
            put("pkg_mgr", "npm", "package.json without lockfile (npm default)")

    # test_cmd
    test_script = scripts.get("test")
    if test_script and test_script.strip() != NPM_DEFAULT_TEST:
        mgr = detected.get("pkg_mgr", "npm")
        put("test_cmd", f"{mgr} test", f"package.json: scripts.test = {test_script!r}")
    elif "pytest" in py or (repo / "pytest.ini").exists() or (repo / "conftest.py").exists() \
            or any((repo / d / "conftest.py").exists() for d in ("tests", "test")):
        put("test_cmd", "python -m pytest", "pytest dependency or config present")

    # integrations
    integ = sorted({INTEGRATION_LIBS[d] for d in alldeps if d in INTEGRATION_LIBS})
    if integ:
        put("integrations", integ, f"SDK dependencies: {integ}")

    unknown = [f for f in REQUIRED + OPTIONAL if f not in detected]
    return {"detected": detected, "evidence": evidence, "unknown": unknown}


def main(argv=None):
    """CLI entry point (I3)."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    result = detect(args.repo)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
