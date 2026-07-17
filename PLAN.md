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
