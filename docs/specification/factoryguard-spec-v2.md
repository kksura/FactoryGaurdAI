# FactoryGuard AI — Engineering Specification v2.0

**Status:** Approved working specification (supersedes the original v1 prompt) 
**Date:** 2026-07-17 · **Owner:** Kalyan Sura · **Prepared by:** Claude (Fable 5), principal ML architect 
**Repository:** `~/ai-tools/projects/FactoryGuardAI`

---

## Amendment summary (v1 → v2)

v2 incorporates the full-architecture review conducted after Phase 2, approved in all three tiers on 2026-07-17. Changes against the original specification:

| # | Change | Rationale | ADR |
|---|--------|-----------|-----|
| A1 | Vision model is a **DINOv2-small frozen encoder + trained head** (was: generic pretrained CNN transfer). A VLM was evaluated and **rejected as the primary vision scorer** | Better embeddings for retrieval/fusion, few-shot capability; VLM fails calibration/latency/attribution requirements | 0018 |
| A2 | **Unsupervised-first serving modes**: `anomaly-only` → `blended` → `supervised`, with cold-start evaluation | Platform is useful before any labels exist, mirroring real deployments | 0019 |
| A3 | **Local assistant layer** (optional, off by default): on-box SLM explanation summarizer and on-box small-VLM triage for abstained images; display/triage only, outputs validated, never decision inputs | On-prem generative assistance without operational authority | 0020 |
| A4 | **TabPFN v2** added as tabular challenger beside HistGradientBoosting primary | Best accuracy-per-effort at ≤30k-row scale; native calibrated probabilities | 0021 |
| A5 | **Modality-dropout training** for both fusion approaches | Missing-modality robustness (Scenario E) trained, not just handled | 0021 |
| A6 | **Optional self-supervised pretraining** (masked reconstruction) for the 1D-CNN sensor encoder | Label-scarce realism; better TS embeddings | 0021 |
| A7 | **Removed:** local event-stream emulator, vector database, feature store | Improvement by subtraction; smaller attack and operations surface | 0021 |
| A8 | Uncertainty method fixed: **conformal prediction + Mahalanobis OOD**; tabular primary fixed: **HistGradientBoosting**; TS model fixed: **1D-CNN encoder + statistical detector** | Decisions closed during modeling review | 0021 |
| A9 | Environment facts baked in: GB10 ARM64, CUDA 13.0, torch 2.9.1+cu130 GPU-verified; **no Azure CLI/credentials — all Azure work is code+docs, unexecuted** | Verified Phase 0/1 findings | — |

---

## 1. Mission and objective

FactoryGuard AI predicts wire-harness manufacturing quality defects **before** end-of-line inspection by fusing four modalities — tabular process data, machine/environmental time series, inspection images, and product/process graph relationships — into calibrated, explainable, policy-governed risk predictions with ranked probable root causes and recommended containment actions.

It is an **advisory system**: it never controls machinery; high-impact recommendations require human approval; no generative model has operational authority.

Targets: local development and benchmarking on an NVIDIA GB10 workstation (ARM64, CUDA 13.0, 121 GiB unified memory); cloud deployment on Microsoft Azure via Microsoft Foundry, Azure Machine Learning, and Azure Container Apps.

For every production unit the system returns: overall defect probability; predicted defect category; severity; confidence; calibrated uncertainty; abstain/refer-to-human decision; serving mode (A2); top contributing signals; ranked probable root causes; similar historical incidents; recommended actions; model/feature versions; data-quality status; timestamps; trace/correlation ID.

The project demonstrates the complete ML lifecycle: data generation → validation → features → training → comparison → calibration → explainability → evaluation → registration → local + cloud inference → monitoring → drift → controlled retraining → secure deployment → rollback.

## 2. Working principles

1. Executable code over pseudocode; no silent TODOs in production paths.
2. Never claim a command/test/scan/deployment succeeded without running and inspecting it (all evidence in `docs/test-evidence.md`).
3. Simple, maintainable technology; local and Azure behavior kept as similar as practical; external services replaceable through interfaces.
4. Runnable without proprietary data — synthetic data only, no real company or personal information.
5. Secrets never in source or Git; least privilege; deny by default; all incoming data and model artifacts treated as untrusted.
6. Dependencies pinned; SBOMs generated; architectural decisions recorded (ADRs 0001–0021).
7. Correctness, security, reproducibility, maintainability first; performance only after measurement.
8. ARM64 compatibility preserved; GPU used when available with a CPU test path everywhere.
9. No public endpoints by default.
10. No language model executes operational actions; recommendations pass deterministic policy validation and human approval.

## 3. Verified environment (Phase 0/1 findings)

| Item | Verified value |
|---|---|
| Host | Dell GB10 workstation, 20-core ARM (Cortex-X925/A725), aarch64 |
| Memory | 121 GiB unified CPU/GPU |
| OS / kernel | Ubuntu 24.04.4 LTS, 6.17-nvidia |
| GPU / CUDA | NVIDIA GB10 (capability 12.1), driver 580.142, CUDA 13.0 |
| PyTorch | 2.9.1+cu130 aarch64 — **GPU matmul verified**; capability-12.1-vs-12.0 warning tracked (OI-1), NGC container is the documented fallback |
| Containers | Docker 29.2.1 + Compose v5, NVIDIA Container Toolkit (GPU passthrough verified) |
| Azure | **No CLI, no credentials** — Phases 7+ produce IaC and runbooks only; every unexecuted cloud step is explicitly marked |

## 4. Business use case

A global wire-harness manufacturer; processes: wire cutting, stripping, crimping, seal insertion, connector assembly, splicing, taping, routing, vision inspection, continuity/high-voltage testing, end-of-line inspection. Defect universe includes crimp height/force anomalies, missing seals, terminal back-out/bending, insulation damage, wrong components/wiring, routing errors, electrical failures, labeling and dimensional/cosmetic issues.

Early risk detection enables: holding suspicious units, lot inspection, machine-setup verification, tool-wear checks, targeted maintenance, instruction validation, scrap/rework reduction, and shipment protection. Advisory only (§2.10).

## 5. Synthetic data system *(implemented, Phase 2)*

Deterministic, seeded generator producing linked, internally consistent datasets.

- **Entities:** plants → lines → work centers → machines → tools; operators (pseudonymous); suppliers → components (connector/terminal/wire/seal) → material lots; product families → products → revisions → BOM edges → routing (9 steps); work orders → production units → process-step events; maintenance, quality labels, defects.
- **Tabular features:** identifiers, shift, cycle time, rates, crimp setpoint/actual, pull force, ambient temp/humidity, tool age & cycles/days since maintenance, changeover duration, units since changeover, recent line defects, timestamps.
- **Time series:** per-unit crimp-force waveform + auxiliary channels (motor current, vibration, temperature, pressure) with baseline shape, noise, drift, faults, tool-wear signatures, dropout (NaN), clipping, phase shifts.
- **Images:** procedural grayscale crimp renderings (assumption A8 — geometric, not photoreal) in 8 visual classes (normal, under/over-crimp, bent terminal, missing seal, surface damage, misalignment, partial insertion) with controlled lighting/rotation/scale/blur/noise/occlusion variation.
- **Graph:** typed edge list (plant/line/machine/tool, supplier/lot, BOM, unit→{product, machine, tool, operator, lots}, defect and maintenance edges) with timestamps for temporal-cutoff features.
- **Causal mechanisms (ground truth for root-cause evaluation):** tool wear; bad supplier lots; humidity×sealing; machine calibration offsets per family; inadequate changeover first-pieces; sensor drift (concealment); maintenance relief; revision shift (OOD); night-shift×load×wear interaction; camera misalignment (image-quality drift). Every defect stores entity-attributed mechanism contributions under `ground_truth/` — a directory the feature pipeline refuses to read.
- **Profiles:** `tiny` (CI, 240 units, 0.2 s), `small` (2.5k units, 2.1 s), `medium` (30k, GB10 benchmark), `large` (200k, cloud). Parquet + PNG + JSON manifests with SHA-256 checksums; identical seed+config ⇒ identical data manifests (tested).
- **Validation:** Pandera schemas, range/reference/time-order/duplicate checks, PNG integrity, quarantine of offending rows with reasons, machine-readable data-quality report; validator proven against injected corruption (tested).

## 6. Data contracts and validation

Pydantic v2 models for API/event payloads; Pandera for dataframes; versioned JSON Schemas for production-unit events, sensor windows, image metadata, prediction requests/responses, feedback, monitoring events. Schema versioning with compatibility tests that fail on breaking changes. Payload size limits, content-type allow-lists, image-format validation, quarantine behavior, data-quality reporting.

## 7. ML problem definition

1. **Binary**: unit fails final inspection.
2. **Multiclass**: most probable defect category (8 categories).
3. **TS anomaly**: abnormal machine cycles/waveforms.
4. **Vision**: normal/defective + defect type.
5. **Root-cause ranking** over machines, tools, suppliers, lots, revisions, parameters, shifts, maintenance state, sensor/image anomalies.
6. **Similar-incident retrieval** by feature/waveform/image-embedding/graph-neighborhood similarity.
7. **Forecasting**: per-line defect rate over a configurable window.
8. **Abstention** → `REVIEW_REQUIRED` on: poor input quality, OOD, uncertainty above threshold, model disagreement, missing required modality, policy violation.
9. **(v2, A2) Serving modes**: `anomaly-only` (no labels yet: statistical TS + image embedding-distance + isolation-forest tabular anomaly under a fixed documented combination rule, conservative abstention), `blended` (labels accumulating; monitored blend weight), `supervised` (full fusion; anomaly scores remain OOD/abstention evidence). Mode appears in every response; cold-start evaluation reports `anomaly-only` performance as if no labels existed.

## 8. Modeling approach (v2)

### 8.1 Baselines (Phase 3)
Rule-based engineering thresholds; majority/prior floor; logistic regression; **HistGradientBoosting (primary tabular)** binary+multiclass with categorical/missing/imbalance handling and SHAP; **TabPFN v2 (challenger, config-switched)**; statistical TS detector (robust z vs healthy envelope + shape features); **DINOv2-small frozen encoder + trained head** (k-NN probe mode) for vision; historical-frequency forecast; isolation-forest + image-distance cold-start scorers.

### 8.2 Time series (Phase 4)
1D-CNN encoder over windowed, mask-aware, train-statistics-normalized waveforms; batched GPU inference; embeddings + anomaly score; deterministic fixtures. **Optional SSL pretraining** (masked-segment reconstruction on unlabeled waveforms) behind a config flag, evaluated against the supervised-only encoder.

### 8.3 Vision (Phase 4, ADR-0018)
DINOv2-small (ViT-S/14) frozen; small trained head; class weights/focal loss; augmentation; embeddings feed retrieval + fusion; Grad-CAM/attention attribution validated against known synthetic defect geometry; ONNX export where clean; robustness tests (blur/rotation/lighting). Pretrained weights pinned + checksummed; fetched at build time only. *A small VLM is explicitly not the primary scorer* (calibration, latency, attribution, determinism, and synthetic-domain transfer all fail — see ADR-0018).

### 8.4 Graph (ADR-0007)
NetworkX feature pipeline with strict temporal cutoffs: neighbor defect rates (time-decayed), supplier-lot risk, machine/tool defect centrality, shared-component risk, path-based similarity. Optional GraphSAGE only after the feature baseline passes; system fully functional with GNN disabled.

### 8.5 Fusion (ADR-0006 + A5)
Late fusion (independently calibrated modality scores + availability mask + per-modality uncertainty → meta-classifier) is the default serving path. Embedding-level fusion (per-modality embeddings + learned "absent" embeddings + gating on availability masks) is the challenger. **Both trained with modality dropout.** Missing modality ≠ zero-valued observation, ever. Comparison is a standard section of the evaluation report.

### 8.6 Calibration, uncertainty, abstention (A8)
Temperature scaling / isotonic on the calibration period; reliability diagrams, ECE, Brier; **conformal prediction** for distribution-free uncertainty; **Mahalanobis distance on embeddings** for OOD; abstention thresholds chosen from operational cost curves; abstention-performance curves reported.

## 9. Evaluation

Temporal + group-aware splitting — train/validation/calibration/test periods plus out-of-time, unseen-line, drifted, missing-modality, and adversarial data-quality test sets. No unit/lot/work-order/machine-cycle/image-set straddles splits; automated leakage tests enforce this.

Metrics: precision/recall/F1, PR-AUC, ROC-AUC, MCC, confusion matrices, per-class performance, cost-weighted error, recall@fixed-FPR, FN-per-million; Brier/ECE/reliability/coverage-vs-risk; forecast MAE/RMSE/MAPE + interval coverage; root-cause Recall@K, MRR, NDCG@K, top-1/top-3 accuracy vs synthetic ground truth; retrieval precision; operational metrics (P50/P95/P99 latency, throughput, GPU/CPU util, memory, model size, startup, abstention rate). **(v2)** Every report includes the TabPFN challenger comparison and the cold-start (`anomaly-only`) section. Acceptance thresholds live in `configs/policies/`, not code.

## 10. Explainability

Tabular SHAP; vision Grad-CAM/attention heatmaps; TS anomalous intervals + influential channels; graph influential entities/paths; nearest historical incidents with distances; fusion modality contributions/gate weights. Reports distinguish statistical association vs model attribution vs known synthetic causal truth vs operational recommendation — attribution is never presented as causation. Human-readable report: prediction, confidence, data-quality warnings, top evidence, competing explanations, similar cases, abstention reason, recommended next steps.

## 11. Recommendations and assistants (v2)

**Recommendation engine:** deterministic, versioned policy rules over an allow-listed action taxonomy (inspect lot, verify crimp height, check tool wear, validate calibration, review first-piece approval, targeted visual inspection, review maintenance, hold unit, escalate). Every recommendation: reason, evidence, policy ID, severity, required approver role, expiration. High-impact actions emit as `PENDING_APPROVAL`; approvals verified from token roles; append-only hash-chained audit log. No recommendation touches machinery.

**Assistant layer (A3, ADR-0020, optional, off by default):**
- *Explanation summarizer:* deterministic `TemplateSummarizer` (default) → optional local SLM on the GB10 → optional hosted Fable 5 via Foundry/Anthropic API.
- *Vision triage:* optional local small VLM (2–3B) invoked only for abstained/borderline images queued for human review and for textual defect descriptions in reports.
- Hard constraints for all assistants: structured-evidence-only input; outputs validated against evidence entities and the action allow-list with template fallback; display/triage layer only; platform fully functional with none configured; outputs marked "generated, advisory".

## 12. Local architecture (GB10)

Modular services (venv for dev, Docker Compose for the stack; loopback-only ports; non-root, cap-dropped containers): synthetic data generator; validation; feature pipelines; training pipelines; MLflow (PostgreSQL backend, MinIO artifacts); registry abstraction; batch + real-time inference (FastAPI); monitoring worker (drift/data quality); Streamlit dashboard; PostgreSQL 16; MinIO; Prometheus + Grafana; OpenTelemetry. **(v2, A7)** No event-stream emulator, no vector DB, no feature store, no Redis — retrieval is exact in-process search; ingestion is batch + REST behind an interface (Event Hubs remains a cloud-phase option).

Stack: Python 3.12, PyTorch 2.9.1+cu130, scikit-learn, MLflow, FastAPI, Pydantic, Pandera, NetworkX, PostgreSQL, MinIO, Prometheus, Grafana, Streamlit, ONNX Runtime (where compatible), ruff/mypy/pytest/hypothesis/bandit/pip-audit/trivy/syft/pre-commit. Unified pip-compile lock (`requirements/lock.txt`) + separately pinned CUDA torch; every dependency checked for ARM64 before adoption.

## 13. Azure target architecture (design only until credentials/cost approval)

- **Identity/governance:** Entra ID, managed identities per role (developer/pipeline/training/deployment/runtime), RBAC least-privilege, PIM recommended, workload identity federation for CI/CD, no shared admin credentials or storage keys.
- **Network:** hub-and-spoke; private endpoints + private DNS for storage/KV/ACR/AML/PostgreSQL; AML managed network isolation; public access disabled; controlled egress via hub firewall; NSGs; Bastion for admin; no public SSH/RDP.
- **Data/artifacts:** ADLS Gen2 (curated data), Blob (images/models), Azure Database for PostgreSQL Flexible (metadata), ACR (containers), AML registry (approved models), Event Hubs only if streaming is enabled, Purview recommended.
- **ML/AI:** Microsoft Foundry project (AI governance, hosted-model access incl. optional Fable 5 summarizer); AML workspace (experiments, pipelines, MLflow tracking, compute clusters, managed online + batch endpoints).
- **Runtime:** Container Apps (API, worker, dashboard — internal ingress, KEDA); API Management for governed exposure; App Gateway/WAF only for deliberate external paths; **AKS explicitly rejected** with documented revisit criteria (ADR-0009).
- **Security/ops:** Key Vault, Defender for Cloud, Sentinel integration, Azure Monitor/Log Analytics/App Insights (OTel), Azure Policy, resource locks, diagnostic settings, retention-protected audit storage, budgets + cost alerts, backup/recovery.
- **IaC:** Bicep primary (modules + per-env parameters, what-if plan-only CI, no secrets in templates, deletion protection for prod); partial Terraform equivalent documented (ADR-0013).

Deliverables: architecture docs + Mermaid diagrams, threat boundaries, port/protocol matrix, identity-to-resource access matrix, deployment/rollback runbooks, teardown scripts. **No deployment executes from the GB10 environment.**

## 14. Security requirements

- **Threat model (STRIDE):** malicious image upload, data/label poisoning, artifact substitution, dependency compromise, container escape, prompt injection (assistants), unauthorized model access, membership inference, model extraction, API abuse, replay, event tampering, privilege escalation, compromised CI, insider misuse, log manipulation, insecure deserialization, DoS, cross-environment access, supply chain. Each material threat: asset, actor, path, likelihood, impact, controls, residual risk, treatment, verification test.
- **API security:** pluggable auth (dev local-JWT — forbidden in hardened envs; Entra ID OIDC in cloud); roles: platform-admin, ml-engineer, data-steward, quality-engineer, plant-viewer, auditor, service; deny-by-default scopes on every route; size limits; content-type allow-list; schema validation; rate limiting; correlation IDs; secure headers; CORS deny-by-default; timeouts; bounded retries; idempotency keys; safe errors (no stack traces).
- **Secrets:** Key Vault + managed identity in cloud; `.env` (ignored) locally with `.env.example` fakes; detect-secrets in pre-commit + CI; redacting log formatter (key- and pattern-based, tested); rotation documented.
- **Encryption:** TLS everywhere; platform-managed keys at rest with CMK documented for high assurance; key/cert lifecycle documented.
- **Supply chain:** unified locked deps; pip-audit/bandit/trivy in CI; SBOM (syft); minimal non-root images, read-only fs, dropped capabilities, no privileged containers; digest pinning in production manifests; image signing + provenance design; CI gates on critical vulns with expiring exceptions. Pretrained weights (DINOv2, TabPFN, optional SLM/VLM) pinned + SHA-256-verified; fetched at build time only.
- **ML security:** dataset + model checksums and lineage; signed promotion metadata; model/dataset cards; training-serving skew detection; poisoning indicators; OOD detection; shadow deployment; human approval before promotion; rollback; prediction logging with privacy controls; feedback validation; safetensors/ONNX preferred, `torch.load` only with `weights_only=True`, joblib only for registry-internal checksum-verified artifacts (ADR-0012).

## 15. Privacy and responsible AI

No real personal data; operators pseudonymous by construction. **Prohibited use: scoring individual workers for employment decisions.** Data minimization, purpose limitation, configurable retention, deletion/export workflows, log redaction, field-classification metadata, bias evaluation across synthetic plants/shifts/product groups, human oversight, feedback appeal/correction, auditability. Deliverables: model card, dataset card (per generated dataset — implemented), impact assessment, limitations.

## 16. Repository structure

As implemented (monorepo): `apps/{api,dashboard,worker}`, `src/factoryguard/{api,auth,config,contracts,data,features,graph,models/{tabular,timeseries,vision,fusion,calibration},explainability,recommendations,inference,monitoring,security,utilities}`, `pipelines/{data,training,evaluation,registration,deployment,monitoring}`, `configs/{data,models,environments,policies}`, `infrastructure/{bicep,terraform,compose,kubernetes}`, `deployment/{local,azureml,container-apps}`, `tests/{unit,integration,contract,security,performance,ml,end_to_end}`, `notebooks/exploration`, `scripts`, `docs/{architecture,operations,security,responsible-ai,adr,performance,specification}`, `sample_data`, `.github/workflows`. Notebooks are exploration-only; production logic lives in tested modules.

## 17. Configuration

Layered: secure defaults → `configs/environments/<env>.yaml` → `FG_*` env vars; validated at startup. Hardened environments (staging/production) **fail to start** on: debug on, docs UI on, auth disabled or dev provider, default/empty credentials, public storage, filesystem storage backend, non-TLS database, unapproved serving alias, checksum verification off, CORS wildcard. No silent fallback from production to development settings. *(Implemented and tested — 9 insecure combinations rejected.)*

## 18. API

Versioned REST: `GET /health/live|ready`, `GET /version`, `POST /api/v1/predictions`, `POST /api/v1/predictions/batch`, `GET /api/v1/predictions/{id}`, `POST /api/v1/feedback`, `GET /api/v1/models/current`, `GET /api/v1/models/{version}/card`, `GET /api/v1/monitoring/summary`, `GET /api/v1/data-quality/summary`. Requests: structured features, image/object references, sensor sequences/references, entity IDs, missing-modality declarations. Responses: schema version, prediction + correlation IDs, model/feature versions, defect probability, per-category probabilities, severity, confidence, uncertainty, abstention status, **serving mode (v2)**, data-quality status, modality availability, top evidence, root-cause ranking, recommended actions, explanation reference, processing time, timestamp. OpenAPI generated and validated in tests.

## 19. Dashboard

Streamlit: plant/line health, current risk, defect-rate trend, confidence and abstention rates, data-quality and drift alerts, top risk factors, root-cause graph view, similar incidents, image explanation overlays, TS anomaly visualization, model performance/version/deployment state, feedback entry, audit view (authorized roles), **serving-mode indicator and advisory-marked assistant outputs (v2)**. Never displays secrets or tokens.

## 20. Observability

OpenTelemetry + structured JSON logs (correlation IDs, redaction) + Prometheus metrics + Grafana dashboards locally; Azure Monitor/App Insights via OTel in cloud. Metrics: request durations, errors, prediction latency (per modality), model-load time, prediction/confidence distributions, abstention rate, input missingness, schema failures, drift indicators, delayed-label performance, GPU/CPU/memory. Recommended Azure alerts: endpoint availability, P95 latency, error rate, data quality, drift, prediction-distribution shift, high abstention, low feedback volume, performance regression, deployment failure, security events, cost anomaly. No images, tokens, or sensitive payloads in logs.

## 21. Drift and retraining

Detectors: feature/prediction/embedding/image-quality/missingness/category-frequency/calibration/performance drift via PSI, JS divergence, KS, Wasserstein, embedding centroid+covariance distance, ECE recomputation (own numpy/scipy implementation — ADR-0016). **Sustained-breach policies**: N consecutive windows + minimum samples + corroborating metrics before a drift event; retraining candidacy requires multiple signals or a performance breach. Retraining workflow: detect → candidate → validate data → train → compare vs champion → security/robustness tests → evaluation report → **human approval** → shadow/canary → monitor → promote or roll back. No automatic promotion, ever.

## 22. MLOps

MLflow tracking (enforced lineage: git commit, dataset version+checksum, feature version, config, seed, lock checksum, hardware, CUDA, duration, metrics, artifacts, signature, input example, cards). Registry stages: Candidate → Validated → Staging → Champion → Archived; promotion gates verify tests, thresholds (from `configs/policies/`), calibration, security scan, checksums, cards, lineage, approver identity; append-only hash-chained event log; serving loads by alias `champion` after manifest verification.

## 23. CI/CD

GitHub Actions (Azure DevOps equivalents documented): 
**PR** — format, lint, types, unit+contract tests, dependency audit, secret scan, SAST, IaC validation, container build+scan, SBOM. 
**Main** — integration tests, tiny-model training test, serialization test, image publish, provenance, optional dev deployment. 
**Release** — full evaluation, candidate registration, approval gate, staging deploy, smoke/load/security tests, canary with progressive traffic, production approval, rollout, automatic rollback on failure signals. 
Workload identity federation; no stored cloud credentials. *(Workflows authored; unexecuted from the GB10 — activates on GitHub push.)*

## 24. Deployment strategy

**Local:** `make setup / doctor / generate-data / validate-data / train-baseline / train-multimodal / evaluate / serve / dashboard / test / test-security / test-performance / up / down / sbom / scan`. 
**Azure:** scripted auth, subscription selection, validation, what-if plan, infra deploy, environment creation, data upload, AML training jobs, model registration, managed online + batch endpoint deployment, smoke tests, traffic shifting (blue/green or canary starting at a small percentage with gate-checked progression), rollback, non-prod teardown. Requires explicit credentials, subscription, region, and cost approval before any execution.

## 25. Performance engineering

GB10 benchmarks (Phase 6): data-generation and loader throughput, GPU utilization, training step time, inference latency (P50/95/99), batch throughput, API throughput, unified-memory peak, container startup, model load. Precision studies: FP32 vs BF16 (FP8/FP4 only if technically valid, with accuracy/calibration comparison — lower precision is never assumed acceptable). Batch-size/worker sweeps; `torch.compile` where supported; ONNX/TensorRT path where reliable. Output: `docs/performance/gb10-benchmark.md` + cloud sizing recommendations derived from measurements, not named SKUs.

## 26. Testing

Unit (generation, features, model I/O, calibration, abstention, policies, security utils, config); property-based (schema invariants, probability ranges, missing modalities, time ordering, idempotency, generator consistency); integration (storage, DB, MLflow, API+model, monitoring, compose); contract (API schemas, events, model signatures, feature schemas); security (authz failures, oversized payloads, invalid content types, path traversal, malformed images, corrupted artifacts, secret leakage, unsafe config, dependency/container scans); ML (leakage, reproducibility, minimum performance, calibration, slices, drift, skew, robustness, missing modality, OOD); end-to-end (generate → validate → train tiny → register → serve → predict → feedback → monitoring). *(Current: 53 unit tests green through Phase 2.)*

## 27. Documentation set

README (tested quick start), architecture docs + diagrams, GB10 setup, data/model design, API guide, Azure deployment guide, security guide + threat model, operations/incident/backup/rollback/drift runbooks, cost guide, responsible-AI set, troubleshooting, contribution guide, `SECURITY.md`, ADRs 0001–0021, this specification. Working-memory files maintained every phase: `PLAN.md`, `docs/implementation-status.md`, `docs/decision-log.md`, `docs/open-issues.md`, `docs/test-evidence.md`, `docs/handoff.md` when needed.

## 28. Demonstration scenarios

A — tool wear raises risk with tool ranked as cause; B — bad supplier lot linked across lines via graph; C — camera misalignment detected as image-quality drift, not defect; D — new revision triggers OOD + higher abstention; E — missing sensor: fusion degrades gracefully, flags modality, lowers confidence; F — malformed/poisoned payload rejected/quarantined; G — candidate with better aggregate accuracy but worse critical-defect recall **fails promotion**; H — shared machine/tool/lot ranked with graph evidence, no causal overclaim. **(v2)** I — cold start: useful anomaly-only predictions with zero labels; J — abstained image triaged by the local VLM assistant (advisory-marked).

## 29. Acceptance criteria

The 25 original criteria stand (tracked in `PLAN.md` with live status), plus v2 additions: (26) cold-start mode evaluated and demonstrated; (27) challenger comparison (TabPFN vs HGB) in the standard report; (28) assistant outputs validated + advisory-marked + fully optional; (29) missing-modality robustness demonstrated with modality-dropout-trained fusion.

## 30. Execution phases and status

| Phase | Scope | Status |
|---|---|---|
| 0 | Discovery, plans, risks, skeleton | ✅ complete (commit 789ff51) |
| 1 | Foundation: locks, config, logging, containers, CI, security tooling | ✅ complete (b779def) — 34 tests |
| 2 | Synthetic data system | ✅ complete (f034864) — 53 tests total |
| 3 | Baselines + evaluation framework (v2 scope) | ▶ next — awaiting go after spec review |
| 4 | Multimodal: embeddings, fusion, calibration, conformal abstention, root cause, retrieval, serving modes | pending |
| 5 | Application: API, policies, dashboard, feedback, audit, assistant layer | pending |
| 6 | MLOps + observability + GB10 benchmark | pending |
| 7 | Azure IaC + AML/Foundry definitions + runbooks (unexecuted by design) | pending |
| 8 | Hardening, scans, SBOM, FINAL-REPORT, demo script | pending |

Each phase ends with: PLAN/status/decision-log updates, tests run and recorded, a meaningful commit, and a concise phase report.

---

*End of specification v2.0. Supersedes the v1 prompt of 2026-07-17; amendments A1–A9 approved by the owner on 2026-07-17.*
