"""Pin pack hashes in packs/PACKS.lock (SPEC P4).

TODO(P4a): this is sha256 pinning, not signing. Cryptographic signing (key custody,
signature format, offline verification) is deferred. Never describe packs as "signed".

Usage: python scripts/sign_pack.py          # rewrite PACKS.lock
       python scripts/sign_pack.py --check  # non-zero exit if any pack differs from the lock
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from packs import LOCK_PATH, PACKS_DIR, file_sha256  # noqa: E402


def compute_lock():
    """sha256 for every pack YAML, keyed by pack id (P4)."""
    return {p.relative_to(PACKS_DIR).with_suffix("").as_posix(): file_sha256(p)
            for p in sorted(PACKS_DIR.rglob("*.yaml"))}


def main(argv=None):
    """CLI (P4)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    lock = compute_lock()
    if args.check:
        current = json.loads(LOCK_PATH.read_text(encoding="utf-8")) if LOCK_PATH.exists() else {}
        if current != lock:
            print("PACKS.lock is stale (P4)", file=sys.stderr)
            return 1
        return 0
    LOCK_PATH.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"pinned {len(lock)} pack(s) in {LOCK_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
