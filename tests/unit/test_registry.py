"""Model registry lifecycle + promotion gates (spec §22, ADR-0005/0017)."""

import json
from pathlib import Path

import pytest

from factoryguard.mlops.registry import ModelRegistry, PromotionError
from factoryguard.security.checksums import write_manifest

GOOD = {"test_roc_auc": 0.60, "test_ece": 0.04, "conformal_coverage": 0.88}
BAD = {"test_roc_auc": 0.48, "test_ece": 0.30, "conformal_coverage": 0.60}


def _artifact_dir(tmp_path: Path, name: str = "bundle") -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "model.joblib").write_bytes(b"fake-model-bytes")
    (d / "lineage.json").write_text(json.dumps({"profile": "tiny"}))
    write_manifest(d, d / "manifest.json")
    return d


def _policy(tmp_path: Path) -> Path:
    p = tmp_path / "promotion.yaml"
    p.write_text(
        "validated:\n  min_test_roc_auc: 0.52\n  max_test_ece: 0.10\n"
        "  min_conformal_coverage: 0.80\n"
        "staging:\n  require_manifest_verified: true\n"
        "champion:\n  required_approver_role: ml-engineer\n"
        "  require_champion_comparison: true\n"
    )
    return p


@pytest.fixture
def registry(tmp_path: Path) -> ModelRegistry:
    return ModelRegistry(tmp_path / "registry", policy_path=_policy(tmp_path))


def test_full_lifecycle_to_champion(registry: ModelRegistry, tmp_path: Path) -> None:
    d = _artifact_dir(tmp_path)
    mid = registry.register(d, GOOD, {"profile": "tiny"}, actor="pipeline")
    registry.promote(mid, "VALIDATED", actor="pipeline")
    registry.promote(mid, "STAGING", actor="eng")
    registry.record_champion_comparison(mid, {"candidate": GOOD, "incumbent": {}}, actor="eng")
    registry.approve(mid, actor="eng", actor_roles=["ml-engineer"])
    entry = registry.promote(mid, "CHAMPION", actor="eng")
    assert entry["stage"] == "CHAMPION"
    assert registry.champion_path() == d
    assert registry.audit.verify() >= 5  # every step audit-chained


def test_metric_gates_reject_bad_candidate(registry: ModelRegistry, tmp_path: Path) -> None:
    mid = registry.register(_artifact_dir(tmp_path), BAD, {}, actor="p")
    with pytest.raises(PromotionError, match="gate failed"):
        registry.promote(mid, "VALIDATED", actor="p")


def test_stage_transitions_enforced(registry: ModelRegistry, tmp_path: Path) -> None:
    mid = registry.register(_artifact_dir(tmp_path), GOOD, {}, actor="p")
    with pytest.raises(PromotionError, match="cannot promote"):
        registry.promote(mid, "CHAMPION", actor="p")  # no stage skipping


def test_champion_requires_approval_and_comparison(registry: ModelRegistry, tmp_path: Path) -> None:
    mid = registry.register(_artifact_dir(tmp_path), GOOD, {}, actor="p")
    registry.promote(mid, "VALIDATED", actor="p")
    registry.promote(mid, "STAGING", actor="p")
    with pytest.raises(PromotionError, match="approval"):
        registry.promote(mid, "CHAMPION", actor="p")
    with pytest.raises(PromotionError, match="requires role"):
        registry.approve(mid, actor="viewer", actor_roles=["plant-viewer"])


def test_tampered_artifact_blocks_staging(registry: ModelRegistry, tmp_path: Path) -> None:
    d = _artifact_dir(tmp_path)
    mid = registry.register(d, GOOD, {}, actor="p")
    registry.promote(mid, "VALIDATED", actor="p")
    (d / "model.joblib").write_bytes(b"tampered!!")
    with pytest.raises(PromotionError, match="verification failed"):
        registry.promote(mid, "STAGING", actor="p")


def test_new_champion_archives_previous(registry: ModelRegistry, tmp_path: Path) -> None:
    def crown(name: str) -> str:
        d = _artifact_dir(tmp_path, name)
        mid = registry.register(d, GOOD, {}, actor="p")
        registry.promote(mid, "VALIDATED", actor="p")
        registry.promote(mid, "STAGING", actor="p")
        registry.record_champion_comparison(mid, {"candidate": GOOD}, actor="p")
        registry.approve(mid, actor="p", actor_roles=["ml-engineer"])
        registry.promote(mid, "CHAMPION", actor="p")
        return mid

    first = crown("m1")
    crown("m2")
    assert registry.get(first)["stage"] == "ARCHIVED"
    assert registry.champion_path() == tmp_path / "m2"
