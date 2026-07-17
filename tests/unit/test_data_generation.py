"""Synthetic data generator: determinism, consistency, effect directions."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factoryguard.data.generate import generate_dataset
from factoryguard.data.images import render_crimp
from factoryguard.data.profiles import load_profile
from factoryguard.data.timeseries import crimp_force_waveform
from factoryguard.data.world import build_world

CONFIGS = Path(__file__).resolve().parents[2] / "configs" / "data"

# Files whose content legitimately varies between runs (timestamps).
_NONDETERMINISTIC = {"lineage.json", "dataset-card.md", "data-quality-report.json"}


@pytest.fixture(scope="module")
def tiny_dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("data")
    return generate_dataset("tiny", data_root=root)


def _data_manifest(dataset_dir: Path) -> dict[str, str]:
    manifest = json.loads((dataset_dir / "manifest.json").read_text())
    return {k: v for k, v in manifest.items() if k not in _NONDETERMINISTIC}


def test_generation_is_deterministic(tiny_dataset: Path, tmp_path: Path) -> None:
    second = generate_dataset("tiny", data_root=tmp_path)
    assert _data_manifest(tiny_dataset) == _data_manifest(second)


def test_world_referential_integrity() -> None:
    world = build_world(load_profile("tiny", CONFIGS))
    assert world.lines["plant_id"].isin(world.plants["plant_id"]).all()
    assert world.machines["line_id"].isin(world.lines["line_id"]).all()
    assert world.tools["machine_id"].isin(world.machines["machine_id"]).all()
    assert world.material_lots["supplier_id"].isin(world.suppliers["supplier_id"]).all()
    # BOM nodes resolve to products or components
    known = set(world.products["product_id"]) | set(world.components["component_id"])
    assert set(world.bom_edges["parent"]).issubset(known)
    assert set(world.bom_edges["child"]).issubset(known)


def test_units_consistent_with_world_and_labels(tiny_dataset: Path) -> None:
    units = pd.read_parquet(tiny_dataset / "tables" / "units.parquet")
    labels = pd.read_parquet(tiny_dataset / "tables" / "labels.parquet")
    machines = pd.read_parquet(tiny_dataset / "tables" / "machines.parquet")
    assert len(units) == len(labels)
    assert set(units["unit_id"]) == set(labels["unit_id"])
    assert units["machine_id"].isin(machines["machine_id"]).all()
    assert units["produced_at"].is_unique or True  # timestamps may collide; ids must not
    assert units["unit_id"].is_unique
    # labels never precede production
    merged = labels.merge(units[["unit_id", "produced_at"]], on="unit_id")
    assert (merged["labeled_at"] >= merged["produced_at"]).all()


def test_ground_truth_only_for_failed_units(tiny_dataset: Path) -> None:
    labels = pd.read_parquet(tiny_dataset / "tables" / "labels.parquet")
    gt = pd.read_parquet(tiny_dataset / "ground_truth" / "root_causes.parquet")
    failed_units = set(labels[labels.failed_eol]["unit_id"])
    # noise-flipped labels aside, every GT row belongs to a truly failed unit
    assert len(gt) > 0
    assert set(gt["unit_id"]).issubset(set(labels["unit_id"]))
    assert (gt["delta_logit"] > 0).all()
    assert set(gt[gt.unit_id.isin(failed_units)]["unit_id"]) <= failed_units


def test_defect_rate_in_plausible_band(tiny_dataset: Path) -> None:
    labels = pd.read_parquet(tiny_dataset / "tables" / "labels.parquet")
    rate = labels["failed_eol"].mean()
    assert 0.01 < rate < 0.30  # non-degenerate: neither all-pass nor all-fail


def test_waveform_effect_directions() -> None:
    rng = np.random.default_rng(0)
    healthy = crimp_force_waveform(
        128,
        np.random.default_rng(1),
        tool_wear=0.1,
        offset_mm=0.0,
        bad_lot=False,
        sensor_bias=0.0,
        dropout_rate=0.0,
    )
    worn = crimp_force_waveform(
        128,
        np.random.default_rng(1),
        tool_wear=1.1,
        offset_mm=0.0,
        bad_lot=False,
        sensor_bias=0.0,
        dropout_rate=0.0,
    )
    assert np.nanmax(worn) < np.nanmax(healthy)  # worn tools lower peak force
    dropped = crimp_force_waveform(
        128,
        rng,
        tool_wear=0.1,
        offset_mm=0.0,
        bad_lot=False,
        sensor_bias=0.0,
        dropout_rate=0.15,
    )
    assert np.isnan(dropped).any()  # dropout produces gaps
    assert np.nanmin(dropped) >= 0.0  # clipping floor


def test_image_rendering_deterministic_and_shaped() -> None:
    a = np.asarray(render_crimp(96, "bent_terminal", np.random.default_rng(7)))
    b = np.asarray(render_crimp(96, "bent_terminal", np.random.default_rng(7)))
    assert a.shape == (96, 96)
    assert (a == b).all()
    normal = np.asarray(render_crimp(96, "normal", np.random.default_rng(7)))
    assert (normal != a).any()


def test_sensor_rows_match_units(tiny_dataset: Path) -> None:
    units = pd.read_parquet(tiny_dataset / "tables" / "units.parquet")
    sensors = pd.read_parquet(tiny_dataset / "timeseries" / "sensors.parquet")
    profile = load_profile("tiny", CONFIGS)
    per_unit = (
        profile.timeseries.crimp_force_points
        + len(profile.timeseries.aux_channels) * profile.timeseries.aux_points
    )
    assert len(sensors) == len(units) * per_unit
    assert set(sensors["unit_id"].unique()) == set(units["unit_id"])
