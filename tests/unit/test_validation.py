"""The validator must catch injected corruption, not just pass clean data."""

from pathlib import Path

import pandas as pd
import pytest

from factoryguard.data.generate import generate_dataset
from factoryguard.data.validation import validate_dataset


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate_dataset("tiny", data_root=tmp_path_factory.mktemp("vdata"))


def test_clean_dataset_passes(dataset: Path) -> None:
    report = validate_dataset(dataset)
    assert report.passed
    assert report.tables["units"].quarantined == 0
    assert (dataset / "data-quality-report.json").is_file()


def _corrupt_copy(dataset: Path, tmp_path: Path) -> Path:
    import shutil

    dst = tmp_path / "corrupt"
    shutil.copytree(dataset, dst)
    return dst


def test_unknown_machine_is_quarantined(dataset: Path, tmp_path: Path) -> None:
    dst = _corrupt_copy(dataset, tmp_path)
    units_path = dst / "tables" / "units.parquet"
    units = pd.read_parquet(units_path)
    units.loc[units.index[:5], "machine_id"] = "M-DOES-NOT-EXIST"
    units.to_parquet(units_path, index=False)
    report = validate_dataset(dst)
    assert report.tables["units"].integrity_violations >= 5
    assert report.tables["units"].quarantined >= 5
    assert not report.passed
    q = pd.read_parquet(dst / "quarantine" / "units.parquet")
    assert (q["_violation"] == "referential_integrity").any()


def test_time_travel_label_detected(dataset: Path, tmp_path: Path) -> None:
    dst = _corrupt_copy(dataset, tmp_path)
    labels_path = dst / "tables" / "labels.parquet"
    labels = pd.read_parquet(labels_path)
    labels.loc[labels.index[:3], "labeled_at"] = labels["labeled_at"].min() - pd.Timedelta(days=400)
    labels.to_parquet(labels_path, index=False)
    report = validate_dataset(dst)
    assert report.tables["step_events"].integrity_violations >= 3


def test_schema_violation_detected(dataset: Path, tmp_path: Path) -> None:
    dst = _corrupt_copy(dataset, tmp_path)
    units_path = dst / "tables" / "units.parquet"
    units = pd.read_parquet(units_path)
    units.loc[units.index[:4], "humidity_pct"] = 250.0  # impossible humidity
    units.to_parquet(units_path, index=False)
    report = validate_dataset(dst)
    assert report.tables["units"].schema_violations >= 4


def test_corrupt_png_detected(dataset: Path, tmp_path: Path) -> None:
    dst = _corrupt_copy(dataset, tmp_path)
    meta = pd.read_parquet(dst / "tables" / "image_metadata.parquet")
    victim = dst / meta.iloc[0]["image_path"]
    victim.write_bytes(b"GIF89a-not-a-png-payload")
    report = validate_dataset(dst)
    assert report.tables["images"].integrity_violations >= 1
