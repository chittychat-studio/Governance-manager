"""Pack loading, hash pinning, signature check and resolution (SPEC P1-P4, P4a, P2a, E8). Deterministic, no network (E2)."""
import hashlib
import json
from pathlib import Path

import miniyaml

ROOT = Path(__file__).resolve().parent.parent
PACKS_DIR = ROOT / "packs"
LOCK_PATH = PACKS_DIR / "PACKS.lock"
ENFORCEMENT = {"enforced", "advisory"}
MECHANISMS = {"deny_rule", "hook", "sandbox", "ci", "instruction"}
AGENTS = {"claude-code", "codex"}


class PackError(ValueError):
    """Pack missing, invalid or hash-mismatched: refuse (P1, P4)."""


def pack_path(pack_id):
    """Map 'tier3/fastapi-postgres/claude-code' to its YAML file (P1)."""
    return PACKS_DIR / f"{pack_id}.yaml"


def file_sha256(path):
    """sha256 of a pack file with CRLF normalised to LF, so Windows checkouts pin the same (P4)."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


_verified = {}


def lock_bytes(path=None):
    """The signed bytes of PACKS.lock: CRLF normalised, so a Windows checkout verifies the same (P4, P4a)."""
    return Path(path or LOCK_PATH).read_bytes().replace(b"\r\n", b"\n")


def check_signature():
    """P4a: when packs/SIGNING_KEY.pub exists, PACKS.lock must carry a valid Ed25519 signature; else refuse.
    Returns True when verified, False when the repo is not signed (hash-pinned only)."""
    pub_p, sig_p = PACKS_DIR / "SIGNING_KEY.pub", PACKS_DIR / "PACKS.lock.sig"
    if not pub_p.exists():
        return False
    data = lock_bytes()
    key = (str(pub_p), hashlib.sha256(data).hexdigest())
    if key in _verified:
        return True
    import ed25519
    try:
        pub = bytes.fromhex(pub_p.read_text(encoding="utf-8").strip())
        sig = bytes.fromhex(sig_p.read_text(encoding="utf-8").strip()) if sig_p.exists() else b""
    except ValueError:
        pub, sig = b"", b""
    if not sig_p.exists() or not ed25519.verify(pub, data, sig):
        raise PackError("refused: packs/PACKS.lock signature is missing or does not verify against "
                        "packs/SIGNING_KEY.pub (P4a). The rule packs may have been tampered with; reinstall Governor "
                        "from its official source.")
    _verified[key] = True
    return True


def signature_status():
    """'signed (verified)' or 'hash-pinned, not signed' (P4a); a bad signature raises."""
    return "signed (verified)" if check_signature() else "hash-pinned, not signed"


def read_lock():
    """Read packs/PACKS.lock written by sign_pack.py, after its signature check (P4, P4a)."""
    if not LOCK_PATH.exists():
        raise PackError("packs/PACKS.lock missing; run scripts/sign_pack.py (P4)")
    check_signature()
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def load_pack(pack_id, lock=None):
    """Load one pack after checking its hash against PACKS.lock; refuse on mismatch (P4)."""
    path = pack_path(pack_id)
    if not path.exists():
        raise PackError(f"refused: no pack for {pack_id} (P1)")
    lock = read_lock() if lock is None else lock
    expected = lock.get(pack_id)
    actual = file_sha256(path)
    if expected is None:
        raise PackError(f"refused: {pack_id} is not pinned in PACKS.lock (P4)")
    if expected != actual:
        raise PackError(f"refused: {pack_id} hash mismatch (P4): lock {expected[:12]} != file {actual[:12]}")
    data = miniyaml.load(path.read_text(encoding="utf-8"))
    validate_pack(data, pack_id)
    return data


def validate_pack(data, pack_id):
    """Check every rule carries the P2 fields with allowed values (P2, P2a)."""
    if data.get("id") != pack_id:
        raise PackError(f"{pack_id}: id field is {data.get('id')!r}")
    seen = set()
    for rule in data.get("rules", []):
        rid = rule.get("id")
        for key in ("id", "spec", "text", "enforcement", "mechanism", "agents"):
            if not rule.get(key):
                raise PackError(f"{pack_id}/{rid}: missing {key} (P2)")
        if rid in seen:
            raise PackError(f"{pack_id}: duplicate rule id {rid}")
        seen.add(rid)
        if rule["enforcement"] not in ENFORCEMENT:
            raise PackError(f"{pack_id}/{rid}: bad enforcement {rule['enforcement']}")
        mech = rule["mechanism"] if isinstance(rule["mechanism"], list) else [rule["mechanism"]]
        if not set(mech) <= MECHANISMS:
            raise PackError(f"{pack_id}/{rid}: bad mechanism {mech}")
        if not set(rule["agents"]) <= AGENTS:
            raise PackError(f"{pack_id}/{rid}: bad agents {rule['agents']}")
        if rule["enforcement"] == "enforced" and mech == ["instruction"]:
            raise PackError(f"{pack_id}/{rid}: an instruction alone cannot be 'enforced' (R6)")
        if rule["enforcement"] == "enforced" and not (rule.get("plain") and rule.get("you_can")):
            raise PackError(f"{pack_id}/{rid}: an enforced rule needs 'plain' and 'you_can' text (P12)")


def resolve(pack_id, lock=None):
    """Resolve the extends chain into (ordered rules, [(pack_id, sha256), ...]) (P3, P4)."""
    lock = read_lock() if lock is None else lock
    chain, rules, pins, cur = [], {}, [], pack_id
    while cur:
        if cur in chain:
            raise PackError(f"extends cycle at {cur}")
        chain.append(cur)
        cur = load_pack(cur, lock).get("extends")
    for pid in reversed(chain):
        data = load_pack(pid, lock)
        pins.append((pid, lock[pid]))
        for rule in data["rules"]:
            if rule["id"] in rules:
                raise PackError(f"{pid}: rule {rule['id']} redefined; packs only add (P3)")
            rules[rule["id"]] = dict(rule, pack=pid)
    return list(rules.values()), pins
