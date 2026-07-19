# Implementation Status

Working-memory file. Update at every phase boundary. Truthful state only — nothing is marked done unless it ran here.

## Current phase
Phase 5 complete. Ready to start Phase 6 (MLflow tracking, registry
abstraction with promotion gates, OTel/Prometheus/Grafana observability,
drift suite, retraining workflow, GB10 benchmark).

## Completed
- 2026-07-17: Phase 0 — environment assessment (GB10 ARM64, CUDA 13.0, Docker+GPU verified), planning docs, repo skeleton, git (commit 789ff51).
- 2026-07-17: Phase 1 — pinned venv (unified lock + torch 2.9.1+cu130, GPU verified), layered fail-closed config, JSON logging with redaction, checksum/manifest utils, Makefile + doctor, Dockerfile + compose stack (validated), pre-commit + secrets baseline, PR CI workflow (written, unexecuted), 17 ADRs.
- 2026-07-17: Phase 2 — full synthetic data system: world model with latent truth separation, 10 causal mechanisms with entity-attributed ground truth, production simulation, sensor waveforms, procedural images, graph edges, 4 profiles, validation+quarantine+report, dataset cards, deterministic manifests.
- 2026-07-17: Architecture review v2 approved (DINOv2 vision, serving modes, assistant layer, TabPFN challenger, scope simplifications) — ADR-0018..0021, spec v2 doc + Word export.
- 2026-07-19: Phase 5 — application layer: contract v1 with golden-schema compat tests; framework-free PredictionService over manifest-verified Phase 4 artifacts (graph entity-rate snapshot for serve-time features); FastAPI with local-JWT auth + 7-role scope model + full middleware stack (size/content-type/rate-limit/headers/safe-errors/idempotency); deterministic recommendation engine (POL-001..008, allow-listed taxonomy, approval-gated high-impact actions) + hash-chained audit log; assistant layer (template default, validated, advisory-marked); Streamlit dashboard; e2e + security + contract test suites. Live-verified: uvicorn boot, 401 without token, full authenticated prediction over HTTP. Also fixed a latent Phase 3 bug: lineage.json was written after the artifact manifest, so strict verification always failed on artifact dirs (D-031).
- 2026-07-17: Phase 4 — multimodal system: graph features (time-decayed, leakage-tested), 1D-CNN TS encoder (mask-aware, optional SSL, best-val-epoch), DINOv2 attention attribution (geometry-validated), Platt/isotonic calibration (D-028), late + embedding fusion with modality dropout (missing ≠ zero, tested), split conformal + Mahalanobis OOD + abstention policy/curves, serving modes with cold-start graph prior, root-cause ranking vs ground truth, exact-search incident retrieval (D-030). Pipeline `train_multimodal` runs tiny/small/medium (medium 59s incl. vision on GB10). Three issues found and fixed during the phase: temperature-only calibration cannot remove balanced-class-weight bias (→ Platt, D-028), an unconstrained Platt slope inverted rankings on a noisy calib slice (→ a>0 constraint), and the binary-trained fused embedding made retrieval worse than random (→ concatenated embeddings, D-030).
- 2026-07-17: Phase 3 — full baseline suite (rule/prior/logistic/HGB+TabPFN/stat-TS/isolation-forest/DINOv2/forecast), leakage-safe temporal+group splits, evaluation report generator, lightweight checksummed artifact persistence. Two real bugs found and fixed during this phase (see decision log D-024/D-025): a generator design flaw that collapsed temporal-split generalization to chance, and an uncalibrated image-quality threshold that detected 0% of degraded images. Both have regression tests now.

## Verified test state
- 155 tests green (unit/ml/contract/security/e2e); ruff + mypy clean (70 source files); bandit: only the 4 pre-accepted LOW findings. Pipelines run on tiny/small/medium; API boots via `make serve` and serves authenticated predictions; dashboard runs under AppTest. See docs/test-evidence.md.

## Known failures / open issues
- See `docs/open-issues.md`.

## Environment constraints (do not forget)
- ARM64 only. No Azure CLI, no cloud credentials → Azure work is unexecuted-by-design.
- CI will run on x86_64 GitHub runners; keep CPU/tiny paths arch-neutral.
