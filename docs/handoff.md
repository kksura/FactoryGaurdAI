# Handoff Note

Updated 2026-07-17 at the end of the Phase 4 session.
Read this first in a new session, then `PLAN.md` and `docs/implementation-status.md`.

## Current phase

**Phases 0–4 complete and committed. Phase 5 (application layer) not yet started.**

## What exists and works right now

- `make setup && make doctor` → healthy venv, torch 2.9.1+cu130, GPU verified on GB10.
- `python -m pipelines.data.generate --profile <tiny|small|medium|large>` → synthetic dataset.
- `python -m pipelines.data.validate --profile <profile>` → validation + quarantine report.
- `python -m pipelines.training.train_baselines --profile <p>` → Phase 3 baselines + report.
- `python -m pipelines.training.train_multimodal --profile <p> [--compare-ssl] [--no-vision]`
  → Phase 4 multimodal system: graph features, TS CNN, vision, calibration, late+embedding
  fusion, conformal+Mahalanobis abstention, serving modes, root-cause ranking, retrieval.
  Writes `reports/evaluation/<p>/multimodal-{report.md,metrics.json}` and checksummed
  artifacts to `artifacts/multimodal/<p>/`. Config: `configs/models/multimodal.yaml`.
- `.venv/bin/pytest tests/unit tests/ml` → 104 tests green; ruff + mypy clean (59 files).

## Next task: Phase 5 — Application (rev. per ADR-0020/0021)

Per `PLAN.md`:
- Contracts (request/response/feedback/events) + JSON Schema versioning + compat tests
- FastAPI app: health/version/predictions/batch/feedback/models/monitoring/data-quality
- Security middleware (auth, roles, size limits, content-type allow-list, rate limit,
  headers, safe errors, idempotency)
- Recommendation engine (versioned policies, allow-listed taxonomy, approver roles, audit log)
- Assistant layer (ADR-0020): TemplateSummarizer default; optional local SLM summarizer +
  local VLM triage behind config, validated outputs, advisory-marked
- Streamlit dashboard (incl. serving-mode + assistant-output panels)
- OpenAPI validation test; e2e test
- Removed scope (do not build): event-stream emulator (ADR-0021)

The Phase 4 artifacts under `artifacts/multimodal/<profile>/` are the models the API
should load (joblib; torch-backed models rebuild from state_dict via their
`__setstate__` — they were persisted on CPU and load without a GPU).

## Things NOT to re-litigate (already decided and approved)

- Late fusion is the default serving path; embedding fusion is the challenger
  (ADR-0006). The winner flips between profiles (small: embedding, medium: late) —
  that comparison lives in the report; the default stays late fusion.
- Uncertainty: conformal + Mahalanobis (never ensembles/MC-dropout).
- Calibration selection rule: isotonic ≥ `min_isotonic_n`, else Platt with the slope
  constrained positive (D-028) — do not "simplify" back to temperature-only (bias bug)
  or unconstrained Platt (rank-inversion bug). Both were hit and fixed this phase.
- Retrieval indexes concatenated modality embeddings, not the fused space (D-030);
  no vector DB (ADR-0021).
- TS encoder keeps the best-val-AUC epoch (D-029); SSL pretraining exists behind
  `ts_encoder.ssl_pretrain` and did NOT help (kept off by default, evidence recorded).

## Gotchas that still matter

1. **`.gitignore` anchoring**: new top-level generated-output dirs need a leading-slash
   pattern; verify with `git check-ignore -v` (see OI-R1 for the original incident).
2. **Bounded time-features only** (D-024): anything derived from elapsed time must decay
   or reset. `tests/ml/test_multimodal.py::test_graph_features_bounded_and_ranges_overlap`
   guards the graph features; extend the guard if new time-derived features appear.
3. **Anomaly scores ≠ probabilities**: `anomaly_metrics` only, `AnomalyScorer` Protocol.
4. **Conformal validity**: calibrators fit on calib-A, conformal/OOD thresholds on
   calib-B (`split_calibration` in `train_multimodal.py`). Never merge them.
5. **TabPFN needs `TABPFN_TOKEN`** (OI-5) — its unavailability is by design here.

## Environment facts (verified, don't re-verify)

- GB10, ARM64, CUDA 13.0, torch 2.9.1+cu130 (capability warning is OI-1, benign so far).
- No Azure CLI/credentials — Phase 7+ is IaC/docs only. No git global identity —
  repo-local identity configured.

## Working-memory files to update every phase

`PLAN.md`, `docs/implementation-status.md`, `docs/decision-log.md`,
`docs/open-issues.md`, `docs/test-evidence.md`, this file.
