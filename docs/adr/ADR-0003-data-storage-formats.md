# ADR-0003: Data storage formats and layout

Status: Accepted · Date: 2026-07-17

## Context
The synthetic data system produces linked tabular entities, high-rate sensor windows, images, and graph relationships, at profiles from `tiny` to `large`, locally (filesystem/MinIO) and later in ADLS Gen2.

## Decision
- **Tabular entities/features/labels**: Parquet (pyarrow), one dataset directory per profile: `data/<profile>/tables/<entity>.parquet`.
- **Time series**: Parquet in long format (`unit_id, step_id, channel, t, value`) partitioned by process step; windows are derived, not stored twice.
- **Images**: PNG files under `data/<profile>/images/<station>/<unit_id>_<view>.png` with a Parquet metadata table (path, labels, generation params).
- **Graph**: edge list + node attribute Parquet tables; NetworkX graph built on demand.
- **Manifests**: every generated dataset directory gets `manifest.json` (SHA-256 per file, generator version, seed, profile config hash) enabling determinism tests and lineage.

## Alternatives
- HDF5/zarr for time series: more machinery; Parquet long format is adequate at these scales and cloud-portable.
- Delta/Iceberg: valuable in production lakes; unnecessary complexity for a reference implementation (documented as an Azure evolution path).

## Consequences
Same layout works on filesystem, MinIO (S3 API), and ADLS Gen2. Checksummed manifests give reproducibility evidence and poisoning detection.

## Security considerations
Manifests double as integrity controls; loaders verify checksums before training (ML security requirement).

## Revisit triggers
`large` profile I/O bottlenecks; need for schema evolution across dataset versions.
