# PLAN — FactoryGuard AI

Status legend: [ ] pending · [~] in progress · [x] done · [!] blocked/needs external environment
Last update: 2026-07-17 (Phase 0)

## Phase 0 — Discovery and design
- [x] Environment inspected (OS, ARM64, Python, GPU, CUDA, Docker+GPU, git, no az) → `docs/environment-assessment.md`
- [x] `docs/implementation-plan.md` with proposed repo tree and tech selections
- [x] `docs/assumptions.md`
- [x] `docs/decision-log.md` (running index; ADRs in `docs/adr/`)
- [x] `docs/risk-register.md`
- [x] Git init, repo-local identity
- [x] `.gitignore`, `.dockerignore`, `.editorconfig`, `.pre-commit-config.yaml`
- [x] Repo skeleton directories
- [~] Architecture docs (`docs/architecture/*.md`) — local done; azure/security/data-flow/topology in Phase 7
- [ ] Threat model (`docs/security/threat-model.md`) — Phase 8
- [x] Phase 0 commit (789ff51)

## Phase 1 — Development foundation
- [x] `pyproject.toml` (project metadata, ruff/mypy/pytest/bandit config)
- [x] Pinned requirements: unified `requirements/lock.txt` (pip-compile, co-resolved) + `torch.txt` (cu130 index)
- [x] `src/factoryguard/config/` layered settings + fail-closed production validation (9 insecure combos tested)
- [x] Structured JSON logging + secret redaction (key- and pattern-based) + correlation IDs
- [x] `Makefile` (all spec §25 targets present; unimplemented pipeline modules fail loudly until their phase)
- [x] `scripts/doctor.py` — verified: torch 2.9.1+cu130, **GPU matmul OK on GB10** (capability 12.1 warning noted, OI-1)
- [x] Dockerfile (multi-stage, non-root uid 10001, healthcheck) + compose stack (postgres/minio/mlflow/prometheus/grafana/api, loopback-only, cap_drop ALL) — `docker compose config` validates
- [x] Pre-commit config (ruff, detect-secrets, bandit, hygiene hooks) + `.secrets.baseline`
- [x] `.github/workflows/pr.yml` (quality, supply-chain, container jobs) — YAML validated; **unexecuted** (no GitHub remote)
- [x] 34 unit tests green; ruff clean; mypy clean (26 files); bandit: 2 low-severity accepted (fixed-argv subprocess in doctor)
- [x] All 17 ADRs written (docs/adr/ADR-0001…0017)

## Phase 2 — Synthetic data ✅ (2026-07-17)
- [x] Entity model + ID scheme (`world.py`: plants→lines→machines→tools; products→BOM; suppliers→lots; latent-truth tables separated under ground_truth/)
- [x] Causal mechanism engine (`mechanisms.py`: all 10 mechanisms, each contribution carries entity attribution for root-cause ground truth)
- [x] Production simulation → units/work_orders/step_events/labels/maintenance Parquet (`units.py`, chronological per line: wear, changeovers, lots, sensor drift)
- [x] Time-series generator (crimp-force waveform + aux channels; noise/drift/dropout-NaN/clipping/phase; wear lowers+widens peak — tested)
- [x] Image generator (procedural crimp renders, 8 visual classes, seeded nuisances; camera-misalignment windows blur without changing labels)
- [x] Graph builder (typed edge list incl. unit→lot/tool/machine/operator, defect and maintenance edges, timestamps for temporal cutoffs)
- [x] Profiles tiny/small/medium/large (`configs/data/*.yaml`); tiny 0.2s, small 2.1s on GB10
- [x] Determinism test: same seed → identical manifests (builtin `hash()` determinism bug found and fixed via `stable_hash`)
- [x] Validation + quarantine + data-quality report; validator proven to catch injected corruption (unknown FK, time travel, schema, corrupt PNG)
- [x] Dataset card + lineage.json + SHA-256 manifest per dataset
- Note: mypy override (`ignore_errors`) scoped to the 4 pandas-heavy simulation modules — pandas-stubs false positives; behaviour covered by tests

## Phase 3 — Baselines + evaluation ✅ (2026-07-17)
- [x] Temporal + group-aware split framework (`evaluation/splits.py`) with 8 automated leakage tests (`tests/ml/test_splits.py`)
- [x] Rule-based baseline; majority/prior floor; logistic regression
- [x] HistGradientBoosting primary (binary + multiclass) + **TabPFN v2 challenger** (config-switched, explicit precondition gates: deps/rows/device/license token)
- [x] Statistical TS anomaly detector (robust z vs healthy envelope + shape features)
- [x] Tabular isolation forest + image embedding-distance anomaly + **image-quality scorer** (cold-start components, ADR-0019) — anomaly/quality scores rank-evaluated only, never reported as calibrated probabilities
- [x] Vision baseline: **DINOv2-small frozen encoder + trained head** (linear + k-NN probe), weights checksum-verified against a pinned SHA-256 before use
- [x] Historical-frequency forecast baseline
- [x] Metrics suite: `classification_metrics`, `anomaly_metrics` (separate — a real conflation bug found and fixed), `multiclass_metrics`, calibration (ECE/reliability curve on the calib split), forecast
- [x] Evaluation report generator: challenger comparison, cold-start section, per-severity recall, image-quality (Scenario C), fit latency + artifact sizes, known limitations
- [x] Lightweight model artifact persistence: joblib + SHA-256 manifest + lineage (git commit, seed, feature version) — not full MLflow/registry (still Phase 6)
- [x] Common model interfaces (`models/interfaces.py`: `ProbabilisticClassifier` / `AnomalyScorer` Protocols)
- **Real bug found and fixed during this phase**: the data generator's tool-wear/maintenance design made `days_since_maintenance`/`tool_age_cycles` unbounded monotonic proxies for elapsed time, collapsing HGB's temporal-split ROC-AUC to chance (0.47-0.50) even though random-CV showed real signal (~0.55-0.57). Fixed via per-tool wear-rate variation, round-robin tool rotation, cycle-counter reset on replacement, and retuned wear_per_cycle across all profiles so multiple wear/maintenance cycles occur within the date range. Regression test added (`tests/ml/test_generalization.py`).
- **Second bug found and fixed**: image-quality blur threshold was an uncalibrated guess (detected 0% of camera-degraded images); recalibrated empirically against real generated data (90% detection / 15% false-flag) with a regression test (`tests/unit/test_image_quality.py`).

## Phase 4 — Multimodal (rev. per ADR-0019/0020/0021)
- [ ] TS embedding model (1D-CNN; **optional SSL masked-reconstruction pretraining**, config flag)
- [ ] Vision embeddings (DINOv2) + Grad-CAM/attention attribution
- [ ] Graph-derived features (neighbor defect rates, lot risk, centrality; temporal cutoffs)
- [ ] Late fusion (calibrated per-modality + meta-classifier) with **modality-dropout training**
- [ ] Embedding fusion (gated, modality masks; missing ≠ zero; modality dropout)
- [ ] Serving modes: anomaly-only / blended / supervised (ADR-0019) reported in responses
- [ ] Calibration (temperature/isotonic) + reliability diagrams + ECE/Brier
- [ ] Uncertainty: **conformal prediction + Mahalanobis OOD** + abstention policy + curves
- [ ] Root-cause ranking + evaluation vs ground truth (top-1/top-3, MRR, NDCG)
- [ ] Similar-incident retrieval (in-process exact search — no vector DB, ADR-0021)

## Phase 5 — Application (rev. per ADR-0020/0021)
- [ ] Contracts (request/response/feedback/events) + JSON Schema versioning + compat tests
- [ ] FastAPI: health/version/predictions/batch/feedback/models/monitoring/data-quality endpoints
- [ ] Security middleware (auth, roles, size limits, content-type allow-list, rate limit, headers, safe errors, idempotency)
- [ ] Recommendation engine (versioned policies, allow-listed taxonomy, approver roles, audit log)
- [ ] Assistant layer (ADR-0020): TemplateSummarizer default; optional local SLM summarizer + local VLM triage behind config, validated outputs, advisory-marked
- [ ] Streamlit dashboard (incl. serving-mode + assistant-output panels)
- [ ] OpenAPI validation test; e2e test
- Removed: local event-stream emulator (ADR-0021) — ingestion stays batch+REST behind an interface

## Phase 6 — MLOps + observability
- [ ] MLflow tracking integration (commit, seeds, checksums, signatures, cards)
- [ ] Registry abstraction: Candidate/Validated/Staging/Champion/Archived + promotion gates
- [ ] OTel instrumentation; Prometheus metrics; Grafana dashboards
- [ ] Drift suite (PSI, JS, KS, Wasserstein; embedding drift; calibration drift)
- [ ] Retraining workflow (sustained breach → candidate → compare → approval → shadow/canary)
- [ ] GB10 benchmark → `docs/performance/gb10-benchmark.md`

## Phase 7 — Azure (design + code, NOT executed here)
- [ ] Bicep: RG, VNet/subnets, private DNS+endpoints, Key Vault, ADLS/Blob, ACR, Log Analytics, App Insights, AML workspace+compute+registry, managed identities, RBAC, PostgreSQL, Event Hubs (flag), Container Apps env, budgets, diagnostics, policy hooks
- [ ] AML job/environment/endpoint YAML; batch endpoint
- [ ] Foundry integration doc; optional Fable 5 summarizer wiring
- [ ] Architecture docs + Mermaid diagrams complete; port/protocol + identity matrices
- [ ] Deployment/rollback runbooks; teardown scripts
- [!] Actual deployment — requires subscription, credentials, cost approval

## Phase 8 — Hardening + final
- [ ] Security test suite (authz, oversized payloads, malformed images, corrupted artifacts, path traversal, secret-leak checks)
- [ ] Performance/load tests + failure injection
- [ ] SBOM (syft), scans (trivy, bandit, pip-audit) with recorded evidence
- [ ] Responsible-AI docs complete
- [ ] `FINAL-REPORT.md` + demo script
- [ ] All 25 acceptance criteria verified or explicitly marked as gaps

## Acceptance criteria tracker (spec §31)
| # | Criterion | Status |
|---|---|---|
| 1 | New developer can run local quick start | pending |
| 2 | Synthetic datasets reproducible | pending |
| 3 | tiny + medium profiles exist | pending |
| 4 | Baseline + multimodal models train | Phase 3 baselines done; multimodal is Phase 4 |
| 5 | Leakage-safe evaluation | done (Phase 3: temporal+group splits, 8 automated tests) |
| 6 | API returns required contract | pending |
| 7 | Missing modalities explicit | pending |
| 8 | Calibration + abstention | pending |
| 9 | Root-cause vs ground truth | pending |
| 10 | Explanations generated | pending |
| 11 | Non-privileged containers | pending |
| 12 | Unit/integration/contract/security/e2e tests | pending |
| 13 | MLflow experiments + artifacts | pending (Phase 6) |
| 14 | Artifact checksums + lineage | done (Phase 3 lightweight persistence); full MLflow lineage in Phase 6 |
| 15 | Scans + SBOM integrated | pending |
| 16 | No secrets in repo | pending |
| 17 | Secure-by-default prod config | pending |
| 18 | Azure infra plannable from code | pending |
| 19 | Private networking + managed identity documented | pending |
| 20 | Rollout + rollback procedure | pending |
| 21 | Monitoring + drift reports | pending |
| 22 | Threat model + RAI docs | pending |
| 23 | No unexplained TODOs in critical paths | pending |
| 24 | Unexecuted cloud ops identified | pending |
| 25 | Final report with gaps | pending |
