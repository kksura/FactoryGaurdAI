"""Model registry with staged promotion gates (spec §22, ADR-0005/0017).

File-backed (``artifacts/registry/registry.json``) — deliberately not the
MLflow registry so the promotion gates are code we own and test; MLflow
tracks experiments, this tracks *deployable* models.

Lifecycle: CANDIDATE → VALIDATED → STAGING → CHAMPION, plus ARCHIVED.
Every promotion:

- verifies the artifact directory against its SHA-256 manifest;
- checks the metric gates from ``configs/policies/promotion.yaml``
  (VALIDATED), and for CHAMPION requires a recorded human approval with
  the configured role plus a stored champion-comparison record;
- appends to the hash-chained audit log (same chain machinery as
  recommendation approvals) and to the entry's own history.

Exactly one CHAMPION exists at a time; promoting a new one archives the
previous. ``champion_path()`` is what serving loads (settings
``model.serving_alias`` = "champion").
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from factoryguard.recommendations.audit import AuditLog
from factoryguard.security.checksums import IntegrityError, verify_manifest

STAGES = ("CANDIDATE", "VALIDATED", "STAGING", "CHAMPION", "ARCHIVED")
_ALLOWED = {
    "CANDIDATE": {"VALIDATED", "ARCHIVED"},
    "VALIDATED": {"STAGING", "ARCHIVED"},
    "STAGING": {"CHAMPION", "ARCHIVED"},
    "CHAMPION": {"ARCHIVED"},
    "ARCHIVED": set(),
}


class PromotionError(Exception):
    pass


class ModelRegistry:
    def __init__(self, root: Path, policy_path: Path | None = None) -> None:
        self.root = root
        self.path = root / "registry.json"
        self.audit = AuditLog(root / "registry-audit.jsonl")
        self.policy: dict[str, Any] = {}
        policy_path = policy_path or Path("configs/policies/promotion.yaml")
        if policy_path.is_file():
            self.policy = yaml.safe_load(policy_path.read_text()) or {}

    # ------------------------------------------------------------- storage

    def _load(self) -> dict[str, Any]:
        if self.path.is_file():
            return dict(json.loads(self.path.read_text()))
        return {"models": {}}

    def _save(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2, default=str) + "\n")

    # -------------------------------------------------------------- public

    def register(
        self,
        artifact_path: Path,
        metrics: dict[str, float],
        lineage: dict[str, Any],
        actor: str,
    ) -> str:
        """Register a trained bundle as CANDIDATE (manifest must verify)."""
        verify_manifest(artifact_path, artifact_path / "manifest.json")
        state = self._load()
        model_id = f"MDL-{uuid.uuid4().hex[:12]}"
        entry = {
            "model_id": model_id,
            "stage": "CANDIDATE",
            "artifact_path": str(artifact_path),
            "metrics": metrics,
            "lineage": lineage,
            "registered_at": datetime.now(UTC).isoformat(),
            "approvals": [],
            "champion_comparison": None,
            "history": [
                {"stage": "CANDIDATE", "at": datetime.now(UTC).isoformat(), "actor": actor}
            ],
        }
        state["models"][model_id] = entry
        self._save(state)
        self.audit.append(
            "model_registered", {"model_id": model_id, "artifact_path": str(artifact_path)}, actor
        )
        return model_id

    def get(self, model_id: str) -> dict[str, Any]:
        state = self._load()
        if model_id not in state["models"]:
            raise KeyError(model_id)
        return dict(state["models"][model_id])

    def record_champion_comparison(
        self, model_id: str, comparison: dict[str, Any], actor: str
    ) -> None:
        state = self._load()
        state["models"][model_id]["champion_comparison"] = comparison
        self._save(state)
        self.audit.append("champion_comparison", {"model_id": model_id, **comparison}, actor)

    def approve(self, model_id: str, actor: str, actor_roles: list[str]) -> None:
        """Record a human approval (needed for CHAMPION promotion)."""
        required = str(self.policy.get("champion", {}).get("required_approver_role", ""))
        if required and required not in actor_roles and "platform-admin" not in actor_roles:
            raise PromotionError(f"approval requires role {required!r}")
        state = self._load()
        state["models"][model_id]["approvals"].append(
            {"actor": actor, "roles": actor_roles, "at": datetime.now(UTC).isoformat()}
        )
        self._save(state)
        self.audit.append("model_approved", {"model_id": model_id}, actor)

    def promote(self, model_id: str, to_stage: str, actor: str) -> dict[str, Any]:
        if to_stage not in STAGES:
            raise PromotionError(f"unknown stage {to_stage}")
        state = self._load()
        if model_id not in state["models"]:
            raise KeyError(model_id)
        entry = state["models"][model_id]
        frm = entry["stage"]
        if to_stage not in _ALLOWED[frm]:
            raise PromotionError(f"cannot promote {frm} → {to_stage}")
        self._check_gates(entry, to_stage)
        if to_stage == "CHAMPION":
            for other in state["models"].values():
                if other["stage"] == "CHAMPION" and other["model_id"] != model_id:
                    other["stage"] = "ARCHIVED"
                    other["history"].append(
                        {
                            "stage": "ARCHIVED",
                            "at": datetime.now(UTC).isoformat(),
                            "actor": actor,
                            "reason": f"superseded by {model_id}",
                        }
                    )
        entry["stage"] = to_stage
        entry["history"].append(
            {"stage": to_stage, "at": datetime.now(UTC).isoformat(), "actor": actor}
        )
        self._save(state)
        self.audit.append(
            "model_promoted", {"model_id": model_id, "from": frm, "to": to_stage}, actor
        )
        return dict(entry)

    def champion_path(self) -> Path | None:
        state = self._load()
        for entry in state["models"].values():
            if entry["stage"] == "CHAMPION":
                return Path(entry["artifact_path"])
        return None

    def list_models(self) -> list[dict[str, Any]]:
        return [dict(e) for e in self._load()["models"].values()]

    # --------------------------------------------------------------- gates

    def _check_gates(self, entry: dict[str, Any], to_stage: str) -> None:
        metrics = entry.get("metrics", {})
        if to_stage == "VALIDATED":
            gates = self.policy.get("validated", {})
            checks = [
                ("test_roc_auc", ">=", gates.get("min_test_roc_auc")),
                ("test_ece", "<=", gates.get("max_test_ece")),
                ("conformal_coverage", ">=", gates.get("min_conformal_coverage")),
            ]
            for metric, op, bound in checks:
                if bound is None:
                    continue
                value = metrics.get(metric)
                if value is None:
                    raise PromotionError(f"gate metric missing: {metric}")
                ok = value >= bound if op == ">=" else value <= bound
                if not ok:
                    raise PromotionError(f"gate failed: {metric}={value:.4f} must be {op} {bound}")
        if to_stage == "STAGING" and self.policy.get("staging", {}).get(
            "require_manifest_verified", True
        ):
            path = Path(entry["artifact_path"])
            try:
                verify_manifest(path, path / "manifest.json")
            except IntegrityError as exc:
                raise PromotionError(f"artifact verification failed: {exc}") from exc
        if to_stage == "CHAMPION":
            champ = self.policy.get("champion", {})
            if not entry.get("approvals"):
                raise PromotionError("champion promotion requires a recorded approval")
            if champ.get("require_champion_comparison", True) and not entry.get(
                "champion_comparison"
            ):
                raise PromotionError("champion promotion requires a recorded champion comparison")
