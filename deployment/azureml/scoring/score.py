"""AML managed-online-endpoint scoring entry (ADR-0008 RemoteScorer target).

Thin adapter only: all behaviour (calibrated fusion, conformal/OOD abstention,
serving modes, root cause, recommendations) lives in the tested
``factoryguard.inference.service.PredictionService`` — the same code path the
local API uses, so local and cloud scoring cannot drift apart.

Unexecuted in the GB10 environment: requires an AML workspace. Validated by
``tests/unit/test_azureml_scoring.py`` against a local artifact bundle.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from factoryguard.contracts.v1 import PredictionRequest
from factoryguard.inference.service import ArtifactBundle, PredictionService
from factoryguard.inference.serving import ServingMode

_service: PredictionService | None = None


def _locate_bundle(model_dir: Path) -> Path:
    """The registered model folder holds one checksum-manifested bundle."""
    manifests = sorted(model_dir.rglob("manifest.json"))
    if not manifests:
        raise FileNotFoundError(f"no manifest.json under {model_dir} — not a FactoryGuard bundle")
    return manifests[0].parent


def init() -> None:
    global _service
    bundle_dir = _locate_bundle(Path(os.environ["AZUREML_MODEL_DIR"]))
    bundle = ArtifactBundle.load(
        bundle_dir,
        verify_checksums=os.environ.get("FG_VERIFY_CHECKSUMS", "true").lower() != "false",
    )
    _service = PredictionService(
        bundle,
        serving_mode=ServingMode(os.environ.get("FG_SERVING_MODE", "supervised")),
    )


def run(raw_data: str) -> dict:
    if _service is None:  # pragma: no cover - AML always calls init() first
        raise RuntimeError("init() has not run")
    request = PredictionRequest.model_validate(json.loads(raw_data))
    response = _service.predict(request)
    return json.loads(response.model_dump_json())
