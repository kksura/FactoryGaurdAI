# ADR-0005: Model registry abstraction with checksummed promotion stages

Status: Accepted · Date: 2026-07-17

## Context
Models need stages (Candidate → Validated → Staging → Champion → Archived), gated promotion with human approval, checksums, lineage, and rollback — locally and on Azure ML registries.

## Decision
A project-owned `ModelRegistry` interface with two implementations:
- **LocalRegistry**: filesystem/MinIO layout `artifacts/registry/<model>/<version>/` containing the artifact tree, `manifest.json` (SHA-256), `model-card.md`, `lineage.json`, and an append-only `events.jsonl` (stage transitions with approver identity and gate results).
- **AzureMLRegistry** (Phase 7): same interface over AML model registry + tags/aliases; unexecuted in this environment.

Promotion API takes a `GateReport` (tests passed, metrics vs thresholds from `configs/policies/`, calibration check, security scan, checksum verification, card+lineage present, approver) and refuses transitions when any gate fails. Serving loads by alias (`champion`) and verifies the manifest before deserialization.

## Alternatives
MLflow Model Registry stages alone: aliases exist, but gate enforcement/approver capture would live in convention rather than code; we still mirror registrations into MLflow for UI visibility.

## Consequences
Deterministic, auditable promotion path testable offline (Scenario G: gate blocks a candidate with worse critical-defect recall). Slight duplication (local layout + MLflow mirror) accepted for enforceability.

## Security considerations
Append-only event log; checksum verification before every load (`IntegrityError` → refuse to serve); no artifact loaded from outside the registry root.

## Revisit triggers
AML registry gains first-class approval workflows we can delegate to; artifact signing (cosign/notation) integration in Phase 8.
