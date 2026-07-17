"""Dataset generation orchestrator.

Writes a complete, checksummed, reproducible dataset:

    data/<profile>/
      tables/*.parquet          public training-visible tables
      timeseries/sensors.parquet
      images/** + tables/image_metadata.parquet
      ground_truth/*.parquet    latent truth — evaluation only, never features
      manifest.json             SHA-256 per file + lineage
      dataset-card.md
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from factoryguard import __version__
from factoryguard.data.graphdata import build_edges
from factoryguard.data.images import generate_images
from factoryguard.data.profiles import Profile, load_profile
from factoryguard.data.timeseries import generate_timeseries
from factoryguard.data.units import simulate_production
from factoryguard.data.world import build_world
from factoryguard.security.checksums import write_manifest

log = logging.getLogger(__name__)


def generate_dataset(profile_name: str, data_root: Path | None = None) -> Path:
    started = time.perf_counter()
    profile = load_profile(profile_name)
    out = (data_root or Path("data")) / profile.profile
    tables_dir = out / "tables"
    gt_dir = out / "ground_truth"
    ts_dir = out / "timeseries"
    for d in (tables_dir, gt_dir, ts_dir):
        d.mkdir(parents=True, exist_ok=True)

    log.info("building world", extra={"profile": profile.profile, "seed": profile.seed})
    world = build_world(profile)
    prod = simulate_production(world, profile)

    log.info("generating sensors", extra={"units": len(prod.units)})
    sensors = generate_timeseries(prod.units, profile)

    log.info("generating images")
    image_meta = generate_images(
        prod.units, prod.labels, world.latent_camera_windows, profile, out / "images"
    )

    edges = build_edges(world, prod)

    public_tables: dict[str, pd.DataFrame] = {
        **world.tables(),
        "work_orders": prod.work_orders,
        "units": prod.units,
        "step_events": prod.step_events,
        "labels": prod.labels,
        "maintenance": prod.maintenance,
        "image_metadata": image_meta,
        "graph_edges": edges,
    }
    for name, df in public_tables.items():
        df.to_parquet(tables_dir / f"{name}.parquet", index=False)
    sensors.to_parquet(ts_dir / "sensors.parquet", index=False)

    prod.ground_truth.to_parquet(gt_dir / "root_causes.parquet", index=False)
    for name, df in world.latent_tables().items():
        df.to_parquet(gt_dir / f"{name}.parquet", index=False)

    lineage = {
        "generator_version": __version__,
        "profile": profile.profile,
        "seed": profile.seed,
        "config_hash": profile.config_hash(),
        "generated_at": datetime.now(UTC).isoformat(),
        "row_counts": {name: int(len(df)) for name, df in public_tables.items()},
        "sensor_rows": int(len(sensors)),
        "defect_rate": float(prod.labels["failed_eol"].mean()),
        "duration_s": round(time.perf_counter() - started, 2),
    }
    (out / "lineage.json").write_text(json.dumps(lineage, indent=2) + "\n")
    _write_dataset_card(out, profile, lineage)
    # Manifest last so it covers every written file (and excludes itself).
    manifest = write_manifest(out, out / "manifest.json")
    log.info("dataset complete", extra={**lineage, "files": len(manifest)})
    return out


def _write_dataset_card(out: Path, profile: Profile, lineage: dict[str, object]) -> None:
    counts = lineage["row_counts"]
    assert isinstance(counts, dict)
    (out / "dataset-card.md").write_text(
        f"""# Dataset Card — FactoryGuard synthetic ({profile.profile})

Generated {lineage["generated_at"]} by generator v{lineage["generator_version"]},
seed {profile.seed}, config hash {lineage["config_hash"]}. Fully synthetic: no real
company, supplier, product, or personal data. Operator IDs are pseudonyms with no
real-world mapping. **Must not be used to evaluate real workers or suppliers.**

## Contents
- {counts.get("units", 0)} production units across {profile.world.plants} plant(s),
  {lineage["defect_rate"]:.1%} observed EOL failure rate
- Sensor rows: {lineage["sensor_rows"]} (crimp-force waveform +
  {len(profile.timeseries.aux_channels)} aux channels/unit)
- Inspection images: {counts.get("image_metadata", 0)} PNG
  ({profile.images.size}px, grayscale, procedural)
- Graph edges: {counts.get("graph_edges", 0)} typed relations
- Ground truth (`ground_truth/`): per-defect mechanism attributions and latent
  tables (bad lots, calibration offsets, shifted revisions, camera windows).
  **Evaluation only — never model features.** Loaders in `factoryguard.features`
  refuse to read this directory.

## Causal mechanisms embedded
tool wear, bad supplier lots, humidity×sealing, machine calibration offsets,
inadequate changeover, sensor drift (concealment), maintenance relief,
revision shift (OOD), night-shift×load interaction, camera misalignment
(image-quality drift). Parameters: see `configs/data/{profile.profile}.yaml`.

## Known limitations
Images are geometric renderings, not photographs (metrics do not transfer to
real cameras). Time gaps, holidays, scrap/rework loops are simplified. Label
noise rate: {profile.labels.label_noise_rate:.1%}; label delay:
{profile.labels.label_delay_days} days.

## Reproduction
`make generate-data PROFILE={profile.profile}` — identical seed+config yields
byte-identical Parquet/PNG content (verified by manifest checksums in CI).
"""
    )
