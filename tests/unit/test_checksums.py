from pathlib import Path

import pytest

from factoryguard.security.checksums import (
    IntegrityError,
    sha256_file,
    verify_file,
    verify_manifest,
    write_manifest,
)


def _make_tree(root: Path) -> None:
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("alpha")
    (root / "sub" / "b.bin").write_bytes(b"\x00\x01\x02")


def test_manifest_roundtrip(tmp_path: Path) -> None:
    tree = tmp_path / "artifact"
    _make_tree(tree)
    manifest = write_manifest(tree, tmp_path / "manifest.json")
    assert set(manifest) == {"a.txt", "sub/b.bin"}
    verify_manifest(tree, tmp_path / "manifest.json")  # must not raise


def test_tampered_file_detected(tmp_path: Path) -> None:
    tree = tmp_path / "artifact"
    _make_tree(tree)
    write_manifest(tree, tmp_path / "manifest.json")
    (tree / "a.txt").write_text("tampered")
    with pytest.raises(IntegrityError, match="checksum mismatch"):
        verify_manifest(tree, tmp_path / "manifest.json")


def test_added_file_detected(tmp_path: Path) -> None:
    tree = tmp_path / "artifact"
    _make_tree(tree)
    write_manifest(tree, tmp_path / "manifest.json")
    (tree / "evil.py").write_text("import os")
    with pytest.raises(IntegrityError, match="file set mismatch"):
        verify_manifest(tree, tmp_path / "manifest.json")


def test_missing_manifest_rejected(tmp_path: Path) -> None:
    with pytest.raises(IntegrityError, match="manifest not found"):
        verify_manifest(tmp_path, tmp_path / "nope.json")


def test_verify_file(tmp_path: Path) -> None:
    f = tmp_path / "model.safetensors"
    f.write_bytes(b"weights")
    digest = sha256_file(f)
    verify_file(f, digest)
    verify_file(f, digest.upper())  # case-insensitive expected digest
    with pytest.raises(IntegrityError):
        verify_file(f, "0" * 64)
