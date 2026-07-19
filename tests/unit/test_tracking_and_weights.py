"""MLflow tracking (file store) + weighted anomaly combination (OI-7)."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from factoryguard.inference.serving import combine_anomaly_scores
from factoryguard.mlops.tracking import log_training_run
from factoryguard.security.checksums import write_manifest


def test_log_training_run_to_file_store(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "m.joblib").write_bytes(b"x")
    write_manifest(artifacts, artifacts / "manifest.json")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "multimodal-metrics.json").write_text("{}")
    results = {
        "fusion": {"late": {"test": {"roc_auc": 0.6, "pr_auc": 0.1, "brier": 0.05, "ece": 0.02}}},
        "uncertainty": {
            "empirical_coverage": 0.88,
            "abstention_rate": 0.09,
            "target_coverage": 0.9,
        },
    }
    lineage = {"profile": "tiny", "seed": 1, "feature_version": "tab-v1", "git_commit": "abc123"}
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    run_id = log_training_run(results, lineage, artifacts, reports, tracking_uri=uri)
    assert run_id
    import mlflow

    run = mlflow.tracking.MlflowClient(tracking_uri=uri).get_run(run_id)
    assert run.data.metrics["fusion.late.test.roc_auc"] == 0.6
    assert run.data.tags["artifact_manifest_sha256"] != "missing"
    assert (reports / "model-card.md").is_file()
    card = (reports / "model-card.md").read_text()
    assert "Advisory" in card and "not causal proof" in card


def test_weighted_anomaly_combination() -> None:
    frame = pd.DataFrame({"stable": [0.2, 0.8, np.nan], "drifted": [0.9, 0.1, np.nan]})
    equal = combine_anomaly_scores(frame)
    np.testing.assert_allclose(equal[:2], [0.55, 0.45])
    weighted = combine_anomaly_scores(frame, weights={"stable": 0.9, "drifted": 0.1})
    assert weighted[0] < equal[0]  # drifted component down-weighted
    assert weighted[1] > equal[1]
    assert np.isnan(weighted[2])  # nothing available → still NaN (abstain)
    # weights renormalize over available components: a row where only the
    # drifted scorer exists still gets a score, not a zero
    frame2 = pd.DataFrame({"stable": [np.nan], "drifted": [0.7]})
    only = combine_anomaly_scores(frame2, weights={"stable": 0.9, "drifted": 0.1})
    np.testing.assert_allclose(only, [0.7])


def test_registry_registered_via_retraining_metric_mapping(tmp_path: Path) -> None:
    """The retraining pipeline's metric mapping must match the gate names."""
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:  # pipelines/ is not an installed package
        sys.path.insert(0, str(repo_root))
    from pipelines.retraining.check_and_retrain import _candidate_metrics

    report = tmp_path / "report"
    report.mkdir()
    (report / "multimodal-metrics.json").write_text(
        json.dumps(
            {
                "fusion": {"late": {"test": {"roc_auc": 0.61, "ece": 0.03}}},
                "uncertainty": {"empirical_coverage": 0.87},
            }
        )
    )
    m = _candidate_metrics(report)
    assert set(m) == {"test_roc_auc", "test_ece", "conformal_coverage"}
