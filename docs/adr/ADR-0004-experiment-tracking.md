# ADR-0004: MLflow for experiment tracking

Status: Accepted · Date: 2026-07-17

## Context
Spec requires MLflow-compatible tracking recording commit, dataset checksums, seeds, config, hardware, metrics, artifacts, signatures, and cards — locally and in Azure.

## Decision
MLflow with a thin project wrapper (`factoryguard.monitoring.tracking`) that enforces the required tags/params on every run (git commit, dataset checksum, feature version, seed, lock-file checksum, hardware, CUDA). Locally: MLflow server container (PostgreSQL backend, MinIO artifacts). In Azure: the AML workspace MLflow endpoint — same client code, different `MLFLOW_TRACKING_URI`.

## Alternatives
W&B/Neptune (SaaS, external data egress), custom tracking (reinvention). Azure ML SDK-native logging (locks local dev to Azure).

## Consequences
Local/cloud parity via MLflow API. The wrapper is the single place enforcing lineage completeness — runs missing required lineage fail fast.

## Security considerations
Tracking server bound to loopback locally; in Azure, AML workspace RBAC + private endpoint. Artifacts checksummed independently of MLflow (ADR-0005).

## Revisit triggers
MLflow major-version breaking changes; org-standard tracking platform emerges.
