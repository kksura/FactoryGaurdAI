"""Local API entry point: `make serve` → uvicorn on 127.0.0.1:8000.

Loads settings (FG_ENVIRONMENT selects the config layer), verifies and
loads the model artifacts for FG_SERVE_PROFILE (default: small), and
serves the app. Fails loudly if artifacts are missing — run
`make train-multimodal PROFILE=small` first.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from factoryguard.api import create_app
from factoryguard.config.settings import load_settings
from factoryguard.inference.service import ArtifactBundle, PredictionService
from factoryguard.inference.serving import ServingMode
from factoryguard.recommendations import AuditLog
from factoryguard.utilities.logging import configure_logging

log = logging.getLogger("apps.api")


def build() -> object:
    settings = load_settings()
    configure_logging(fmt=settings.monitoring.log_format)
    profile = os.environ.get("FG_SERVE_PROFILE", "small")
    artifacts = Path("artifacts/multimodal") / profile
    if settings.model.serving_alias == "champion":
        from factoryguard.mlops.registry import ModelRegistry

        champion = ModelRegistry(Path("artifacts/registry")).champion_path()
        if champion is not None:
            artifacts = champion
            log.info("serving registry champion from %s", artifacts)
        else:
            log.info("no registry champion yet; serving profile artifacts %s", artifacts)
    bundle = ArtifactBundle.load(artifacts, verify_checksums=settings.model.verify_checksums)
    service = PredictionService(
        bundle,
        serving_mode=ServingMode(os.environ.get("FG_SERVING_MODE", "supervised")),
        storage_root=Path("data") / profile,
        enable_vision=os.environ.get("FG_ENABLE_VISION", "0") == "1",
        log_dir=Path("artifacts/serving-logs"),
    )
    audit = AuditLog(Path("artifacts/audit/audit-log.jsonl"))
    log.info("serving %s in %s mode", bundle.model_version, service.mode.value)
    return create_app(settings, service, audit)


app = build()

if __name__ == "__main__":
    import uvicorn

    settings = load_settings()
    uvicorn.run(app, host=settings.api.host, port=settings.api.port)
