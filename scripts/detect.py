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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from intake import OPTIONAL, REQUIRED  # noqa: E402

SKIP_DIRS = {".git", ".governor", ".claude", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build",
             ".next", ".mypy_cache", ".pytest_cache", "site-packages", ".tox"}
SOURCE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".sql", ".prisma", ".mjs", ".cjs"}
MAX_FILE_BYTES = 200_000
MAX_FILES = 3000

PY_DB = {"psycopg", "psycopg2", "psycopg2-binary", "asyncpg", "psycopg-binary"}
NODE_DB = {"pg", "postgres", "pg-promise"}
# P1a, P11: hosted backends vibe-coded apps use; the stack becomes e.g. next-supabase, react-vite-firebase.
NODE_BACKENDS = (("supabase", {"@supabase/supabase-js", "@supabase/ssr", "@supabase/auth-helpers-nextjs"}),
                 ("firebase", {"firebase", "firebase-admin"}))
AUTH_LIBS = {"passlib", "python-jose", "pyjwt", "fastapi-users", "bcrypt", "authlib", "argon2-cffi",
             "jsonwebtoken", "passport", "bcryptjs", "next-auth", "express-session", "@auth/core",
             "@clerk/nextjs", "@clerk/clerk-react", "better-auth", "lucia", "@supabase/auth-helpers-nextjs"}
PAYMENT_LIBS = {"stripe", "@stripe/stripe-js", "braintree", "paypalrestsdk", "@paypal/checkout-server-sdk",
                "@lemonsqueezy/lemonsqueezy.js", "@paddle/paddle-js", "@paddle/paddle-node-sdk"}
HEALTH_LIBS = {"fhir.resources", "fhirclient", "hl7", "hl7apy", "fhir-kit-client"}
INTEGRATION_LIBS = {"stripe": "stripe", "@stripe/stripe-js": "stripe", "supabase": "supabase",
                    "@supabase/supabase-js": "supabase", "openai": "openai", "anthropic": "anthropic",
                    "@anthropic-ai/sdk": "anthropic", "sendgrid": "sendgrid", "@sendgrid/mail": "sendgrid",
                    "twilio": "twilio", "boto3": "aws", "@aws-sdk/client-s3": "aws"}
PUBLIC_DEPLOY_FILES = ["vercel.json", "netlify.toml", "fly.toml", "render.yaml", "railway.json",
                       "app.yaml", "Procfile", "firebase.json", "wrangler.toml"]
PII_RE = re.compile(r"\b(email|phone|phone_number|date_of_birth|dob|home_address|postcode|zip_code|ssn|"
                    r"national_insurance(?:_number)?|first_name|last_name|full_name)\b"
                    r"(?:\s*[:=(]|\s+(?:text|varchar|char|citext|date)\b)", re.I)
TENANT_RE = re.compile(r"\b(tenant_id|organization_id|org_id|workspace_id)\b", re.I)
NPM_DEFAULT_TEST = 'echo "Error: no test specified" && exit 1'


HEALTH_RE = re.compile(r"\b(diagnosis|medical_record(?:_number)?|patient_id|nhs_number|icd_?10|prescription|mrn|"
                       r"blood_type|allergies)\b(?:\s*[:=(]|\s+(?:text|varchar|char|date)\b)", re.I)
PAYMENT_RE = re.compile(r"\b(card_number|cardholder_name|cvv|iban|sort_code|bank_account_number)\b"
                        r"(?:\s*[:=(]|\s+(?:text|varchar|char)\b)", re.I)
PG_EXTRA_RE = re.compile(r"^(sqlalchemy|databases|sqlmodel|tortoise-orm|piccolo)\[[^\]]*(postgres|asyncpg|psycopg)", re.I)
COMPOSE_PG_RE = re.compile(r"^\s*image:\s*[\"']?(postgres|postgis/postgis|bitnami/postgresql)\b", re.I | re.M)
MAX_DEPTH = 2


SAFE_NAME = re.compile(r"[^A-Za-z0-9._/@+-]")


def safe_name(name, cap=80):
    """A repo-supplied name as quoted data for agent-facing output (L1a): restricted characters, capped length."""
    s = SAFE_NAME.sub("?", str(name))
    return "'" + (s if len(s) <= cap else s[:cap - 3] + "...") + "'"


def _read(path):
    """Read a user file as text; tolerant of a UTF-8 BOM (Windows Notepad) and bad bytes."""
    return Path(path).read_text(encoding="utf-8-sig", errors="ignore")


def _norm(name):
    """Normalise a Python requirement string to its package name (I3)."""
    return re.split(r"[\s<>=!~\[;@]", name.strip().lower(), maxsplit=1)[0]


def manifest_dirs(repo):
    """The repo root and subdirectories up to MAX_DEPTH deep, skipping vendored/build dirs (I3)."""
    out = [repo]
    frontier = [repo]
    for _ in range(MAX_DEPTH):
        nxt = []
        for d in frontier:
            try:
                children = sorted(c for c in d.iterdir() if c.is_dir() and not c.is_symlink())
            except OSError:
                continue
            for c in children:
                if c.name in SKIP_DIRS or c.name.startswith("."):
                    continue
                nxt.append(c)
        out += nxt
        frontier = nxt
    return out


def _requirements(path, repo, deps, extras, seen):
    if path in seen or not path.is_file():
        return
    seen.add(path)
    try:
        rel = path.relative_to(repo).as_posix()
    except ValueError:
        return  # an include outside the repo is not evidence about this repo
    for line in _read(path).splitlines():
        line = line.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(-r|-c|--requirement|--constraint)\s*=?\s*(\S+)", line)
        if m:
            _requirements((path.parent / m.group(2)).resolve(), repo, deps, extras, seen)
            continue
        if line.startswith("-"):
            continue
        deps.setdefault(_norm(line), rel)
        if PG_EXTRA_RE.match(line):
            extras.setdefault("postgres", f"{safe_name(rel)}: postgres extra on {safe_name(_norm(line))}")


def _pyproject_names(data):
    names = list(data.get("project", {}).get("dependencies", []))
    for group in data.get("project", {}).get("optional-dependencies", {}).values():
        names.extend(group)
    for group in data.get("dependency-groups", {}).values():
        names.extend(x for x in group if isinstance(x, str))
    tool = data.get("tool", {})
    poetry = tool.get("poetry", {})
    names.extend(poetry.get("dependencies", {}).keys())
    names.extend(poetry.get("dev-dependencies", {}).keys())
    for group in poetry.get("group", {}).values():
        names.extend(group.get("dependencies", {}).keys())
    names.extend(tool.get("uv", {}).get("dev-dependencies", []))
    for group in tool.get("pdm", {}).get("dev-dependencies", {}).values():
        names.extend(group)
    for name, spec in poetry.get("dependencies", {}).items():
        if isinstance(spec, dict) and any(re.search("postgres|asyncpg|psycopg", e) for e in spec.get("extras", [])):
            names.append(f"{name}[postgresql]")
    return [str(n) for n in names]


def read_python_deps(repo, extras=None):
    """Collect Python dependency names with their source file, across manifest dirs (I3)."""
    import tomllib  # stdlib since 3.11; imported lazily so intake's version check reports first
    deps, extras, seen = {}, ({} if extras is None else extras), set()
    for d in manifest_dirs(repo):
        for req in sorted(d.glob("requirements*.txt")) + sorted((d / "requirements").glob("*.txt")):
            _requirements(req.resolve(), repo, deps, extras, seen)
        pyproject = d / "pyproject.toml"
        if pyproject.is_file():
            try:
                data = tomllib.loads(_read(pyproject))
            except tomllib.TOMLDecodeError:
                data = {}
            rel = pyproject.relative_to(repo).as_posix()
            for n in _pyproject_names(data):
                deps.setdefault(_norm(n), rel)
                if PG_EXTRA_RE.match(n):
                    extras.setdefault("postgres", f"{safe_name(rel)}: postgres extra on {safe_name(_norm(n))}")
            if data.get("tool", {}).get("pytest"):
                deps.setdefault("pytest", rel)
        for compose in sorted(d.glob("docker-compose*.y*ml")) + sorted(d.glob("compose*.y*ml")):
            if COMPOSE_PG_RE.search(_read(compose)):
                extras.setdefault("postgres", f"{safe_name(compose.relative_to(repo).as_posix())}: postgres image")
    return deps


def read_package_json(repo):
    """Return (deps {name: file}, scripts of the first package.json with a test script) (I3)."""
    deps, scripts = {}, {}
    for d in manifest_dirs(repo):
        pkg = d / "package.json"
        if not pkg.is_file():
            continue
        try:
            data = json.loads(_read(pkg))
        except json.JSONDecodeError:
            continue
        rel = pkg.relative_to(repo).as_posix()
        for key in ("dependencies", "devDependencies"):
            for n in data.get(key, {}) or {}:
                deps.setdefault(n.lower(), rel)
        if not scripts and d == repo:
            scripts = data.get("scripts", {}) or {}
    return deps, scripts


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

    extras = {}
    py = read_python_deps(repo, extras)
    node, scripts = read_package_json(repo)
    alldeps = {**py, **node}

    # stack + app_type
    framework = app_type = None
    for name, fw, at in (("fastapi", "fastapi", "api"), ("django", "django", "fullstack"),
                         ("flask", "flask", "api"), ("next", "next", "fullstack"), ("nuxt", "nuxt", "fullstack"),
                         ("@sveltejs/kit", "sveltekit", "fullstack"), ("@remix-run/react", "remix", "fullstack"),
                         ("astro", "astro", "fullstack"), ("@nestjs/core", "nest", "api"),
                         ("express", "node-express", "api")):
        if name in alldeps:
            framework, app_type = fw, at
            src = safe_name(alldeps[name])
            break
    if framework is None and "react" in node and "vite" in node:
        framework, app_type, src = "react-vite", "web-spa", "package.json"
    elif framework is None and ("react-scripts" in node or "react" in node):
        framework, app_type, src = "react", "web-spa", "package.json"
    elif framework is None and "vite" in node:
        framework, app_type, src = "vite", "web-spa", "package.json"
    elif framework is None and node:
        framework, app_type, src = "node", None, "package.json"
    if framework:
        db = None
        if PY_DB & set(py) or NODE_DB & set(node):
            db = "postgres"
            dbsrc = f"postgres driver {sorted((PY_DB & set(py)) | (NODE_DB & set(node)))}"
        elif "postgres" in extras:
            db, dbsrc = "postgres", extras["postgres"]
        else:
            for name, libs in NODE_BACKENDS:
                hit = sorted(libs & set(node))
                if hit:
                    db, dbsrc = name, f"{name} SDK {hit}"
                    break
        put("stack", f"{framework}-{db}" if db else framework,
            f"{src}: {framework} dependency" + (f"; {dbsrc}" if db else ""))
        if app_type:
            put("app_type", app_type, f"{src}: {framework} implies {app_type}")

    # data_classes (only positive evidence; never infer 'none')
    classes = []
    for cls, libs in (("auth", AUTH_LIBS), ("payments", PAYMENT_LIBS), ("health", HEALTH_LIBS)):
        hits = sorted(libs & set(alldeps))
        if hits:
            classes.append(cls)
            evidence.setdefault("data_classes", []).append(f"{safe_name(alldeps[hits[0]])}: {cls} library {hits}")
    found = {}
    scans = {"pii": PII_RE, "health": HEALTH_RE, "payments": PAYMENT_RE, "tenant": TENANT_RE}
    for f in iter_source_files(repo):
        text = _read(f)
        for key, rx in scans.items():
            if key not in found:
                m = rx.search(text)
                if m:
                    found[key] = (f.relative_to(repo).as_posix(), m.group(1))
        if len(found) == len(scans):
            break
    for cls in ("pii", "health", "payments"):
        if cls in found:
            classes.append(cls)
            evidence.setdefault("data_classes", []).append(f"{safe_name(found[cls][0])}: {cls} field {safe_name(found[cls][1])}")
    if classes:
        detected["data_classes"] = sorted(set(classes))

    # exposure: only 'public' is detectable (a public hosting config)
    for name in PUBLIC_DEPLOY_FILES:
        if (repo / name).exists():
            put("exposure", "public", f"{name}: public hosting config")
            break

    # tenancy: only 'multi' is detectable
    if "tenant" in found:
        put("tenancy", "multi", f"{safe_name(found['tenant'][0])}: tenant key {safe_name(found['tenant'][1])}")

    # agent
    agents = []
    claude_markers = ["CLAUDE.md", ".claude/CLAUDE.md", ".claude/settings.json", ".claude/settings.local.json",
                      ".claude/rules", ".claude/skills", ".claude/commands", ".claude/agents"]
    found = [m for m in claude_markers if (repo / m).exists()]
    if found:
        agents.append("claude-code")
        evidence.setdefault("agent", []).append(f"Claude Code config present: {found[0]}")
    if (repo / "AGENTS.md").exists() or (repo / ".codex").is_dir():
        agents.append("codex")
        evidence.setdefault("agent", []).append("AGENTS.md or .codex/ present")
    if agents:
        detected["agent"] = agents

    # conventions.pkg_mgr
    locks = [(d, lock, mgr) for d in manifest_dirs(repo)
             for lock, mgr in (("uv.lock", "uv"), ("poetry.lock", "poetry"), ("pnpm-lock.yaml", "pnpm"),
                               ("yarn.lock", "yarn"), ("package-lock.json", "npm")) if (d / lock).exists()]
    py_first = "fastapi" in py or "django" in py or "flask" in py
    locks.sort(key=lambda x: (x[2] not in ("uv", "poetry")) if py_first else (x[2] in ("uv", "poetry")))
    if locks:
        d, lock, mgr = locks[0]
        put("pkg_mgr", mgr, f"{safe_name((d / lock).relative_to(repo).as_posix())} present")
    else:
        if py:
            put("pkg_mgr", "pip", "requirements*.txt present")
        elif node:
            put("pkg_mgr", "npm", "package.json without lockfile (npm default)")

    # test_cmd
    test_script = scripts.get("test")
    mgr = detected.get("pkg_mgr")
    has_pytest = "pytest" in py or (repo / "pytest.ini").exists() or (repo / "conftest.py").exists() \
        or any((repo / d / "conftest.py").exists() for d in ("tests", "test"))
    if has_pytest and (py_first or not test_script):
        runner = {"uv": "uv run pytest", "poetry": "poetry run pytest"}.get(mgr, "python -m pytest")
        put("test_cmd", runner, f"pytest dependency or config present; package manager {mgr or 'pip'}")
    elif test_script and test_script.strip() != NPM_DEFAULT_TEST:
        node_mgr = mgr if mgr in ("npm", "pnpm", "yarn") else "npm"
        put("test_cmd", f"{node_mgr} test", "package.json: scripts.test is set (its text is not shown, L1a; "
            "the Stop hook runs it, so review it yourself)")

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
