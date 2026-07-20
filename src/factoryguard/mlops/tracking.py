"""MLflow experiment tracking (spec §22, ADR-0004; acceptance #13).

Logs every multimodal training run: parameters (profile, seed, config),
flattened headline metrics, tags (git commit, feature versions, artifact
manifest digest), and the evaluation report + model card as artifacts.

Defaults to a local serverless sqlite backend (``sqlite:///mlruns/mlflow.db``
— MLflow 3.14 deprecated the plain file store) so tracking works with no
services running; point ``tracking_uri`` at the compose MLflow server to
log there instead. MLflow import stays inside the function — it is heavy
and the training pipeline must work with tracking disabled.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from factoryguard.security.checksums import sha256_file

log = logging.getLogger(__name__)

_HEADLINE = (
    ("fusion.late.test.roc_auc", ("fusion", "late", "test", "roc_auc")),
    ("fusion.late.test.pr_auc", ("fusion", "late", "test", "pr_auc")),
    ("fusion.late.test.brier", ("fusion", "late", "test", "brier")),
    ("fusion.late.test.ece", ("fusion", "late", "test", "ece")),
    ("fusion.embedding.test.roc_auc", ("fusion", "embedding", "test", "roc_auc")),
    ("uncertainty.empirical_coverage", ("uncertainty", "empirical_coverage")),
    ("uncertainty.abstention_rate", ("uncertainty", "abstention_rate")),
    ("root_cause.mrr", ("root_cause", "mrr")),
    ("root_cause.hit_at_3", ("root_cause", "hit_at_3")),
    ("retrieval.precision_at_k", ("retrieval", "precision_at_k")),
    ("serving.anomaly_only.test.roc_auc", ("serving", "anomaly_only", "test", "roc_auc")),
)


def _dig(results: dict[str, Any], path: tuple[str, ...]) -> float | None:
    node: Any = results
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return float(node) if isinstance(node, int | float) else None


def log_training_run(
    results: dict[str, Any],
    lineage: dict[str, Any],
    artifacts_dir: Path,
    report_dir: Path,
    tracking_uri: str = "sqlite:///mlruns/mlflow.db",
    experiment: str = "factoryguard-multimodal",
    extra_params: dict[str, Any] | None = None,
) -> str:
    """Log one training run; returns the MLflow run id."""
    import mlflow

    if tracking_uri.startswith("sqlite:///"):
        Path(tracking_uri.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment)
    run_name = f"{lineage.get('profile')}-{lineage.get('git_commit', '')[:8]}"
    with mlflow.start_run(run_name=run_name) as run:
        mlflow.log_params(
            {
                "profile": lineage.get("profile"),
                "seed": lineage.get("seed"),
                "feature_version": lineage.get("feature_version"),
                **(extra_params or {}),
            }
        )
        mlflow.set_tags(
            {
                "git_commit": lineage.get("git_commit", "unknown"),
                "artifact_manifest_sha256": _manifest_digest(artifacts_dir),
                "created_at": lineage.get("created_at", ""),
            }
        )
        for name, path in _HEADLINE:
            value = _dig(results, path)
            if value is not None:
                mlflow.log_metric(name, value)
        for artifact in ("multimodal-report.md", "multimodal-metrics.json"):
            p = report_dir / artifact
            if p.is_file():
                mlflow.log_artifact(str(p))
        card = _model_card(results, lineage)
        card_path = report_dir / "model-card.md"
        card_path.write_text(card)
        mlflow.log_artifact(str(card_path))
        log.info("mlflow run %s logged to %s", run.info.run_id, tracking_uri)
        return str(run.info.run_id)


def _manifest_digest(artifacts_dir: Path) -> str:
    manifest = artifacts_dir / "manifest.json"
    return sha256_file(manifest) if manifest.is_file() else "missing"


def _model_card(results: dict[str, Any], lineage: dict[str, Any]) -> str:
    late = results.get("fusion", {}).get("late", {}).get("test", {})
    unc = results.get("uncertainty", {})
    return "\n".join(
        [
            "# Model Card — FactoryGuard multimodal fusion",
            "",
            f"- Profile: `{lineage.get('profile')}` · seed {lineage.get('seed')} · "
            f"commit `{lineage.get('git_commit', '')[:12]}`",
            f"- Feature version: {lineage.get('feature_version')}",
            "",
            "## Intended use",
            "Advisory wire-harness defect-risk scoring. Never a control system; "
            "anomaly/blended risk scores are not probabilities.",
            "",
            "## Headline evaluation (temporal test period)",
            f"- Late fusion ROC-AUC {late.get('roc_auc', float('nan')):.3f} · "
            f"PR-AUC {late.get('pr_auc', float('nan')):.3f} · "
            f"Brier {late.get('brier', float('nan')):.4f} · "
            f"ECE {late.get('ece', float('nan')):.3f}",
            f"- Conformal coverage {unc.get('empirical_coverage', float('nan')):.1%} "
            f"(target {unc.get('target_coverage', 0.9):.0%}) · "
            f"abstention {unc.get('abstention_rate', float('nan')):.1%}",
            "",
            "## Limitations",
            "- Trained on synthetic data; real-world transfer unvalidated.",
            "- Conformal coverage assumes exchangeability; drift erodes it.",
            "- Root-cause rankings are statistical association, not causal proof.",
            "- TS supervised head is ≈ chance under temporal drift (reported).",
        ]
    )
