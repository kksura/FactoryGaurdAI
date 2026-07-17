"""SHA-256 integrity utilities for datasets and model artifacts.

Model and dataset artifacts are treated as untrusted until their checksum
matches the manifest recorded at production time (see SECURITY.md).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

_CHUNK = 1 << 20  # 1 MiB


class IntegrityError(Exception):
    """An artifact failed integrity verification. Never load it."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_tree(root: Path, pattern: str = "**/*") -> dict[str, str]:
    """Checksums for every file under ``root``, keyed by POSIX relative path."""
    return {
        p.relative_to(root).as_posix(): sha256_file(p)
        for p in sorted(root.glob(pattern))
        if p.is_file()
    }


def write_manifest(root: Path, manifest_path: Path) -> dict[str, str]:
    """Write a checksum manifest for a directory tree and return it."""
    manifest = sha256_tree(root)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def verify_manifest(root: Path, manifest_path: Path) -> None:
    """Raise :class:`IntegrityError` if any file is missing, extra, or altered."""
    if not manifest_path.is_file():
        raise IntegrityError(f"manifest not found: {manifest_path}")
    expected: dict[str, str] = json.loads(manifest_path.read_text())
    actual = sha256_tree(root)
    if set(expected) != set(actual):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise IntegrityError(f"file set mismatch (missing={missing[:5]}, extra={extra[:5]})")
    for rel, digest in expected.items():
        # hmac.compare_digest: constant-time comparison as a habit for digests.
        if not hmac.compare_digest(digest, actual[rel]):
            raise IntegrityError(f"checksum mismatch for {rel}")


def verify_file(path: Path, expected_sha256: str) -> None:
    """Raise :class:`IntegrityError` unless ``path`` hashes to ``expected_sha256``."""
    actual = sha256_file(path)
    if not hmac.compare_digest(actual, expected_sha256.lower()):
        raise IntegrityError(f"checksum mismatch for {path.name}: {actual} != {expected_sha256}")
