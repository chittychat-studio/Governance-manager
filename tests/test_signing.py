"""P4a: Ed25519 against RFC 8032 test vectors, and pack-lock signature enforcement."""
import os
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import ed25519  # noqa: E402
import packs  # noqa: E402

# RFC 8032 section 7.1, TEST 1, TEST 2, TEST 3 (secret key, public key, message, signature; hex).
VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]


@pytest.mark.parametrize("sk,pk,msg,sig", VECTORS)
def test_rfc8032_vectors(sk, pk, msg, sig):
    sk, pk, msg, sig = map(bytes.fromhex, (sk, pk, msg, sig))
    assert ed25519.public_key(sk) == pk
    assert ed25519.sign(sk, msg) == sig
    assert ed25519.verify(pk, msg, sig)
    assert not ed25519.verify(pk, msg + b"x", sig)
    assert not ed25519.verify(pk, msg, sig[:-1] + bytes([sig[-1] ^ 1]))


def _signed_pack_dir(tmp_path, monkeypatch):
    """A copy of packs/ signed with a throwaway key, wired into packs.py."""
    import shutil
    d = tmp_path / "packs"
    shutil.copytree(ROOT / "packs", d)
    for f in ("PACKS.lock.sig", "SIGNING_KEY.pub"):
        (d / f).unlink(missing_ok=True)
    seed = os.urandom(32)
    (d / "SIGNING_KEY.pub").write_text(ed25519.public_key(seed).hex() + "\n")
    (d / "PACKS.lock.sig").write_text(ed25519.sign(seed, packs.lock_bytes(d / "PACKS.lock")).hex() + "\n")
    monkeypatch.setattr(packs, "PACKS_DIR", d)
    monkeypatch.setattr(packs, "LOCK_PATH", d / "PACKS.lock")
    packs._verified.clear()
    return d, seed


def test_valid_signature_is_accepted_and_reported(tmp_path, monkeypatch):
    d, _ = _signed_pack_dir(tmp_path, monkeypatch)
    assert packs.read_lock()
    assert packs.signature_status() == f"signed (verified), key {packs.key_fingerprint()}"
    assert len(packs.key_fingerprint()) == 16


def test_tampered_lock_is_refused(tmp_path, monkeypatch):
    d, _ = _signed_pack_dir(tmp_path, monkeypatch)
    lock = d / "PACKS.lock"
    lock.write_text(lock.read_text().replace('"tier1/generic/claude-code": "', '"tier1/generic/claude-code": "0'))
    with pytest.raises(packs.PackError, match="signature"):
        packs.read_lock()


def test_missing_signature_is_refused_when_key_exists(tmp_path, monkeypatch):
    d, _ = _signed_pack_dir(tmp_path, monkeypatch)
    (d / "PACKS.lock.sig").unlink()
    with pytest.raises(packs.PackError, match="signature"):
        packs.read_lock()


def test_signature_by_another_key_is_refused(tmp_path, monkeypatch):
    d, _ = _signed_pack_dir(tmp_path, monkeypatch)
    other = os.urandom(32)
    (d / "PACKS.lock.sig").write_text(ed25519.sign(other, packs.lock_bytes(d / "PACKS.lock")).hex())
    with pytest.raises(packs.PackError, match="signature"):
        packs.read_lock()


def test_unsigned_repo_says_hash_pinned():
    if (ROOT / "packs" / "SIGNING_KEY.pub").exists():
        pytest.skip("repo is signed")
    assert packs.signature_status() == "hash-pinned, not signed"
