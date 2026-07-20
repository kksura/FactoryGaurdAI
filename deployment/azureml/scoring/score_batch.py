"""AML batch-endpoint scoring entry: JSONL files of PredictionRequest lines in,
one JSON-serialized PredictionResponse per line out (``append_row``).

Reuses the identical service layer as ``score.py``; a malformed line raises and
fails the file — with ``error_threshold: 0`` the run stops loudly rather than
emitting silently partial output.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from score import _locate_bundle  # noqa: F401 - same code directory at runtime

from factoryguard.contracts.v1 import PredictionRequest
from factoryguard.inference.service import ArtifactBundle, PredictionService
from factoryguard.inference.serving import ServingMode

_service: PredictionService | None = None


def init() -> None:
    global _service
    bundle_dir = _locate_bundle(Path(os.environ["AZUREML_MODEL_DIR"]))
    bundle = ArtifactBundle.load(bundle_dir, verify_checksums=True)
    _service = PredictionService(
        bundle,
        serving_mode=ServingMode(os.environ.get("FG_SERVING_MODE", "supervised")),
    )


def run(mini_batch: list[str]) -> list[str]:
    if _service is None:  # pragma: no cover - AML always calls init() first
        raise RuntimeError("init() has not run")
    rows: list[str] = []
    for file_path in mini_batch:
        for line in Path(file_path).read_text().splitlines():
            if not line.strip():
                continue
            request = PredictionRequest.model_validate(json.loads(line))
            rows.append(_service.predict(request).model_dump_json())
    return rows
