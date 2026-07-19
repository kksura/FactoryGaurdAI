"""Append-only hash-chained audit log (spec §11).

JSONL file where each entry commits to its predecessor:

    entry_hash = SHA-256(prev_hash + canonical_json(payload))

``verify()`` walks the chain and raises on any tamper (edited, removed or
reordered entries all break the chain). The log records recommendation
emissions and approval decisions — identity, action, decision — never
token contents (ADR-0010 logging rule).
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

_GENESIS = "0" * 64


class AuditIntegrityError(Exception):
    pass


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        if not self.path.is_file() or self.path.stat().st_size == 0:
            return _GENESIS
        with self.path.open("rb") as fh:
            last = b""
            for line in fh:
                if line.strip():
                    last = line
        return str(json.loads(last)["entry_hash"])

    @staticmethod
    def _canonical(payload: dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    def append(self, event_type: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        with self._lock:
            prev = self._last_hash()
            entry: dict[str, Any] = {
                "ts": datetime.now(UTC).isoformat(),
                "event_type": event_type,
                "actor": actor,
                "payload": payload,
                "prev_hash": prev,
            }
            entry["entry_hash"] = sha256(
                (
                    prev + self._canonical({k: v for k, v in entry.items() if k != "prev_hash"})
                ).encode()
            ).hexdigest()
            with self.path.open("a") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
            return entry

    def verify(self) -> int:
        """Walk the chain; return the entry count or raise AuditIntegrityError."""
        if not self.path.is_file():
            return 0
        prev = _GENESIS
        count = 0
        for i, line in enumerate(self.path.read_text().splitlines()):
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("prev_hash") != prev:
                raise AuditIntegrityError(f"chain break at entry {i}: prev_hash mismatch")
            expected = sha256(
                (
                    prev
                    + self._canonical(
                        {k: v for k, v in entry.items() if k not in ("prev_hash", "entry_hash")}
                    )
                ).encode()
            ).hexdigest()
            if entry.get("entry_hash") != expected:
                raise AuditIntegrityError(f"tampered entry {i}: hash mismatch")
            prev = entry["entry_hash"]
            count += 1
        return count

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        return [json.loads(ln) for ln in self.path.read_text().splitlines() if ln.strip()]
