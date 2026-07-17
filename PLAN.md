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
- [~] `.gitignore`, `.dockerignore`, `.editorconfig`, `.pre-commit-config.yaml`
- [~] Repo skeleton directories
- [ ] Architecture docs (`docs/architecture/*.md`) — seeded in Phase 0, completed by Phase 7
- [ ] Threat model (`docs/security/threat-model.md`) — seeded Phase 0/1, completed Phase 8
- [ ] Phase 0 commit + report

## Phase 1 — Development foundation
- [ ] `pyproject.toml` (project metadata, ruff/mypy/pytest config)
- [ ] Pinned requirements (`requirements/*.txt` compiled lock, hashes where possible)
- [ ] `src/factoryguard/config/` layered settings + production startup validation (fail-closed)
- [ ] Structured JSON logging + secret redaction + correlation IDs
- [ ] `Makefile` (setup, doctor, test, lint, …)
- [ ] `scripts/doctor.py` (GPU/CUDA/deps health check)
- [ ] Dockerfile (non-root, multi-stage, arm64) + `docker-compose.yml` (postgres, minio, mlflow, prometheus, grafana)
- [ ] Pre-commit (ruff, mypy, detect-secrets, bandit)
- [ ] `.github/workflows/pr.yml` baseline CI
- [ ] Unit tests for config/logging/security utils; `make test` green

## Phase 2 — Synthetic data
- [ ] Entity model + ID scheme (plants→lines→machines→tools; products→connectors→terminals→wires; suppliers→lots; units→process steps)
- [ ] Causal mechanism engine (tool wear, supplier lot, humidity, calibration offset, changeover, sensor drift, maintenance effect, revision shift, shift×load interaction, camera misalignment)
- [ ] Tabular generator → Parquet
- [ ] Time-series generator (crimp force, current, vibration, temp, …) with noise/drift/faults/dropout
- [ ] Image generator (procedural crimp images, 8 defect classes, seeded perturbations)
- [ ] Graph builder (NetworkX, typed edges)
- [ ] Profiles: tiny/small/medium/large via `configs/data/*.yaml`
- [ ] Determinism: same seed → identical checksums (test)
- [ ] Validation pipeline (Pandera schemas, referential integrity, time order, quarantine) + data-quality report
- [ ] Dataset card

## Phase 3 — Baselines + evaluation
- [ ] Temporal + group-aware split framework with leakage tests
- [ ] Rule-based baseline; logistic regression; HistGradientBoosting (binary + multiclass)
- [ ] Statistical TS anomaly detector (robust z / spectral)
- [ ] Lightweight CNN (transfer learning) vision baseline
- [ ] Historical-frequency forecast baseline
- [ ] Metrics suite (PR-AUC, ROC-AUC, MCC, recall@FPR, cost-weighted, per-class, calibration, forecast, retrieval)
- [ ] Evaluation report generator

## Phase 4 — Multimodal
- [ ] TS embedding model (1D-CNN/AE) + anomaly score
- [ ] Vision embeddings + Grad-CAM
- [ ] Graph-derived features (neighbor defect rates, lot risk, centrality)
- [ ] Late fusion (calibrated per-modality + meta-classifier)
- [ ] Embedding fusion (gated, modality masks; missing ≠ zero)
- [ ] Calibration (temperature/isotonic) + reliability diagrams + ECE/Brier
- [ ] Uncertainty (ensemble or conformal) + abstention policy + curves
- [ ] Root-cause ranking + evaluation vs ground truth (top-1/top-3, MRR, NDCG)
- [ ] Similar-incident retrieval (embedding + graph neighborhood)

## Phase 5 — Application
- [ ] Contracts (request/response/feedback/events) + JSON Schema versioning + compat tests
- [ ] FastAPI: health/version/predictions/batch/feedback/models/monitoring/data-quality endpoints
- [ ] Security middleware (auth, roles, size limits, content-type allow-list, rate limit, headers, safe errors, idempotency)
- [ ] Recommendation engine (versioned policies, allow-listed taxonomy, approver roles, audit log)
- [ ] Streamlit dashboard
- [ ] OpenAPI validation test; e2e test

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
| 4 | Baseline + multimodal models train | pending |
| 5 | Leakage-safe evaluation | pending |
| 6 | API returns required contract | pending |
| 7 | Missing modalities explicit | pending |
| 8 | Calibration + abstention | pending |
| 9 | Root-cause vs ground truth | pending |
| 10 | Explanations generated | pending |
| 11 | Non-privileged containers | pending |
| 12 | Unit/integration/contract/security/e2e tests | pending |
| 13 | MLflow experiments + artifacts | pending |
| 14 | Artifact checksums + lineage | pending |
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
