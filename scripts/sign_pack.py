"""Pin pack hashes in packs/PACKS.lock and sign it (SPEC P4, P4a).

Usage: python scripts/sign_pack.py                       # rewrite PACKS.lock (hash pins)
       python scripts/sign_pack.py --check               # non-zero exit if any pack differs from the lock
       python scripts/sign_pack.py --new-key PATH        # maintainer, once: create a signing key outside the repo
       python scripts/sign_pack.py --sign-key PATH       # rewrite PACKS.lock and sign it (writes PACKS.lock.sig)
The private key is a 32-byte seed file. Keep it outside the repository and never commit it; only
packs/SIGNING_KEY.pub is committed.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ed25519  # noqa: E402
from packs import LOCK_PATH, PACKS_DIR, ROOT, file_sha256, lock_bytes  # noqa: E402

PUB = PACKS_DIR / "SIGNING_KEY.pub"
SIG = PACKS_DIR / "PACKS.lock.sig"


def compute_lock():
    """sha256 for every pack YAML, keyed by pack id (P4)."""
    return {p.relative_to(PACKS_DIR).with_suffix("").as_posix(): file_sha256(p)
            for p in sorted(PACKS_DIR.rglob("*.yaml"))}


def _safe_key_path(path):
    p = Path(path).expanduser().resolve()
    if ROOT.resolve() in p.parents or p == ROOT.resolve():
        raise SystemExit("refused: keep the signing key outside the repository so it is never committed (P4a)")
    if (Path.home() / ".claude").resolve() in p.parents:
        raise SystemExit("refused: never write to ~/.claude (E6); pick another folder for the key")
    return p


def new_key(path):
    p = _safe_key_path(path)
    if p.exists():
        raise SystemExit(f"refused: {p} already exists; not overwriting a key")
    seed = os.urandom(32)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(seed)
    PUB.write_text(ed25519.public_key(seed).hex() + "\n", encoding="utf-8")
    print(f"key written to {p} (keep it private and backed up); public key in packs/{PUB.name}")


def sign(path):
    seed = _safe_key_path(path).read_bytes()
    if len(seed) != 32:
        raise SystemExit("refused: the key file must hold exactly 32 bytes")
    pub = ed25519.public_key(seed).hex()
    if PUB.exists() and PUB.read_text(encoding="utf-8").strip() != pub:
        raise SystemExit("refused: this key does not match packs/SIGNING_KEY.pub")
    SIG.write_text(ed25519.sign(seed, lock_bytes()).hex() + "\n", encoding="utf-8")
    print(f"signed {LOCK_PATH.name} -> packs/{SIG.name}")


def main(argv=None):
    """CLI (P4, P4a)."""
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--new-key")
    ap.add_argument("--sign-key")
    args = ap.parse_args(argv)
    if args.new_key:
        new_key(args.new_key)
        return 0
    lock = compute_lock()
    if args.check:
        current = json.loads(LOCK_PATH.read_text(encoding="utf-8")) if LOCK_PATH.exists() else {}
        if current != lock:
            print("PACKS.lock is stale (P4)", file=sys.stderr)
            return 1
        return 0
    LOCK_PATH.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"pinned {len(lock)} pack(s) in {LOCK_PATH.name}")
    if args.sign_key:
        sign(args.sign_key)
    elif PUB.exists():
        print(f"WARNING: packs are signed but {LOCK_PATH.name} changed; re-sign with --sign-key PATH, "
              "or installs will refuse (P4a)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
