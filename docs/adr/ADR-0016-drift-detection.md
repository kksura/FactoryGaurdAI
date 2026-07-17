# ADR-0016: Drift detection approach

Status: Accepted · Date: 2026-07-17

## Context
Feature/prediction/embedding/image-quality/calibration/performance drift must be detected without hair-trigger retraining on single noisy metrics.

## Decision
Project-owned drift module (`factoryguard.monitoring.drift`) computing per-window statistics against a frozen reference window: PSI and JS divergence (categorical + binned numeric), KS and Wasserstein (numeric), missingness deltas, prediction/confidence distribution shift, embedding centroid + covariance distance, ECE recomputation when labels arrive. Decisions use **sustained-breach policies** from `configs/policies/drift.yaml`: a metric must breach for N consecutive windows AND a minimum sample count before a drift event is raised; retraining candidacy additionally requires multiple corroborating metrics or a performance breach. Implemented on numpy/scipy directly (no evidently/alibi dependency) for ARM64 safety and testability against synthetic drift scenarios with known ground truth.

## Alternatives
Evidently (heavy transitive deps, moving API), alibi-detect (TF-leaning). Both re-evaluable later behind the same interface.

## Consequences
Full control and deterministic tests (Scenario C/D use generator-injected drift with known onset); we own statistical correctness (mitigated by property tests vs scipy references).

## Security considerations
Drift events are signals into the *human-gated* retraining workflow — never auto-promotion (spec §21).

## Revisit triggers
Need for advanced OOD detectors (e.g. Mahalanobis on embeddings is already planned; deep OOD only if metrics demand).
