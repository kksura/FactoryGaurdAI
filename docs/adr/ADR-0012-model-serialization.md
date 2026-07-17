# ADR-0012: Model serialization

Status: Accepted · Date: 2026-07-17

## Context
Pickle-based formats are code-execution vectors. Spec: avoid unsafe loading; if pickle is unavoidable, only integrity-verified internal artifacts.

## Decision
- Torch models: `state_dict` saved as **safetensors** (weights) + a JSON architecture/config file; reconstruction is code-driven, never pickled objects. `torch.load` is banned except with `weights_only=True` on internal legacy files (enforced by a lint/security test).
- sklearn models: joblib pickle is unavoidable → allowed **only** for artifacts written by our registry, loaded **only** after SHA-256 manifest verification from the registry root; a future migration to ONNX/skops is noted.
- Exchange/serving-optimized format: ONNX where export is clean (vision, fusion meta-model), with parity tests vs the native model.

## Alternatives
skops (limited estimator coverage), pure-ONNX everything (export gaps for some estimators/custom layers).

## Consequences
Loaders are centralized in `factoryguard.security.artifacts` + registry; scattered `joblib.load`/`torch.load` calls are flagged in review/tests.

## Security considerations
Checksum-before-deserialize is mandatory and tested (corrupted-artifact security test); artifact paths are constrained to the registry root (no traversal).

## Revisit triggers
skops maturity; ONNX opset coverage for all served models; artifact signing rollout.
