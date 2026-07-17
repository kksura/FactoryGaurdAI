# Implementation Plan

FactoryGuard AI — multimodal defect-risk prediction for wire-harness manufacturing.
Local target: NVIDIA GB10 (ARM64, CUDA 13.0, 121 GiB unified memory). Cloud target: Azure (Foundry + Azure ML), design/IaC only in this environment (no Azure CLI/credentials — see `docs/environment-assessment.md`).

## Delivery strategy

Depth-first vertical slices inside a phased plan: each phase produces something runnable and tested before the next phase starts. Working memory is kept in `PLAN.md`, `docs/implementation-status.md`, `docs/decision-log.md`, `docs/open-issues.md`, `docs/test-evidence.md`.

## Proposed repository tree

```text
FactoryGuardAI/
├── apps/
│   ├── api/                    # FastAPI entrypoint (thin; logic in src/)
│   ├── dashboard/              # Streamlit operational dashboard
│   └── worker/                 # monitoring / batch-scoring worker
├── src/factoryguard/
│   ├── api/                    # routers, dependencies, middleware
│   ├── auth/                   # provider interface, local JWT issuer, roles/scopes
│   ├── config/                 # layered pydantic-settings, startup validation
│   ├── contracts/              # pydantic models + versioned JSON Schemas
│   ├── data/                   # synthetic generator, ingestion, validation, quarantine
│   ├── features/               # tabular/timeseries/image/graph feature pipelines
│   ├── graph/                  # graph construction + graph-derived features
│   ├── models/
│   │   ├── tabular/            # rule baseline, logistic, HGB
│   │   ├── timeseries/         # stat detector, 1D-CNN/autoencoder
│   │   ├── vision/             # CNN transfer learning, Grad-CAM
│   │   ├── fusion/             # late fusion + embedding fusion w/ modality masks
│   │   └── calibration/        # temperature scaling, isotonic, conformal
│   ├── explainability/         # SHAP, Grad-CAM, TS intervals, report builder
│   ├── recommendations/        # deterministic policy engine + allow-list taxonomy
│   ├── inference/              # predictor service, abstention, batch scorer
│   ├── monitoring/             # metrics, drift (PSI/JS/KS), data-quality reports
│   ├── security/               # checksums, artifact verification, secret redaction
│   └── utilities/              # seeding, io, time, ids
├── pipelines/                  # runnable pipeline entrypoints (data/training/eval/…)
├── configs/                    # yaml: data profiles, models, environments, policies
├── infrastructure/
│   ├── bicep/                  # primary IaC (modules + environments)
│   ├── terraform/              # partial equivalent, documented
│   └── compose/                # docker-compose fragments, prometheus/grafana config
├── deployment/
│   ├── local/                  # local serve scripts
│   ├── azureml/                # AML job/endpoint/environment YAML (unexecuted)
│   └── container-apps/         # Container Apps definitions (unexecuted)
├── tests/{unit,integration,contract,security,performance,end_to_end,ml}/
├── notebooks/exploration/      # exploration only, no production logic
├── scripts/                    # doctor.py, gen_data.sh, sbom.sh, scan.sh, …
├── docs/{architecture,operations,security,responsible-ai,adr,performance}/
├── sample_data/                # tiny committed sample for docs/tests
├── .github/workflows/          # pr.yml, main.yml, release.yml
├── pyproject.toml  Makefile  docker-compose.yml
├── README.md  PLAN.md  CHANGELOG.md  SECURITY.md
```

## Technology selections (summary — details in ADRs)

| Concern | Local | Azure | ARM64 status |
|---|---|---|---|
| Language | Python 3.12 | same | native |
| DL | PyTorch (aarch64 CUDA wheel; NGC fallback) | AML GPU cluster | verify sm_121 at `make doctor` |
| Classical ML | scikit-learn | same | wheels available |
| Tabular boost | sklearn HistGradientBoosting (no lightgbm/xgboost build risk) | same | pure sklearn |
| Tracking | MLflow (local server, MinIO artifact store) | AML MLflow endpoint | image + wheels OK |
| API | FastAPI + uvicorn | Container Apps | pure Python |
| Validation | Pydantic v2, Pandera | same | OK |
| DB | PostgreSQL 16 (container) | Azure Database for PostgreSQL Flexible | official arm64 image |
| Object store | MinIO (container) / filesystem abstraction | ADLS Gen2 + Blob | official arm64 image |
| Graph | NetworkX (+optional PyG off by default) | same | NetworkX pure Python |
| Vision | DINOv2-small frozen encoder + trained head (ADR-0018) | same | torch/torchvision aarch64 OK |
| Tabular challenger | TabPFN v2, config-switched (ADR-0021) | same | torch-based, verify at adoption |
| Vision explain | Grad-CAM / attention attribution (own implementation) | same | OK |
| Assistants (optional) | Template default; local SLM/VLM via on-box runtime (ADR-0020) | Foundry-hosted option | off by default |
| Observability | OpenTelemetry SDK, Prometheus, Grafana | Azure Monitor + App Insights (OTel exporter) | arm64 images OK |
| Dashboard | Streamlit | Container Apps | pure Python |
| Quality/security tooling | ruff, mypy, pytest, hypothesis, bandit, pip-audit, detect-secrets, trivy (container), syft (container) | CI equivalents | trivy/syft publish arm64 binaries |

## Phase plan and exit criteria

| Phase | Scope | Exit criteria (measurable) |
|---|---|---|
| 0 Discovery | env assessment, plan, risks, skeleton, git | docs exist; repo tree created; initial commit |
| 1 Foundation | pyproject + lock, config, logging, Makefile, Dockerfile, compose, CI, pre-commit | `make setup && make doctor && make test` green locally; ruff/mypy clean |
| 2 Synthetic data | entities, causal mechanisms, tabular/TS/images/graph, validation, profiles | `make generate-data PROFILE=tiny/small` deterministic (same seed → same checksums); validation report produced; unit + property tests green |
| 3 Baselines | rule, logistic, HGB, stat-TS, small CNN, frequency forecast; split framework; metrics | `make train-baseline` runs on small profile; leakage tests green; evaluation report artifact |
| 4 Multimodal | embeddings, graph features, two fusion modes, calibration, uncertainty, abstention, root-cause, retrieval | fusion beats best single modality on synthetic test; ECE reported; abstention curve; root-cause Recall@3 vs ground truth |
| 5 Application | API (full response contract), policy recommendations, dashboard, feedback, audit | OpenAPI validated in tests; e2e test: generate→train tiny→serve→predict→feedback passes |
| 6 MLOps/obs | MLflow, registry+checksums+stages, OTel/Prometheus/Grafana, drift, retraining workflow | drift report generated on drifted scenario; promotion gate demonstrably blocks Scenario G |
| 7 Azure | Bicep modules, AML YAML, Foundry docs, runbooks | `bicep build` (containerized) passes; every cloud step marked unexecuted; deployment guide complete |
| 8 Hardening | security/perf/failure tests, SBOM, scans, FINAL-REPORT | bandit/pip-audit/trivy run with recorded results; SBOM generated; FINAL-REPORT.md complete |

## Acceptance criteria

The 25 acceptance criteria from the specification are tracked one-by-one in `PLAN.md` and verified in `FINAL-REPORT.md`. Thresholds (model metrics, latency) live in `configs/` (e.g. `configs/policies/acceptance.yaml`), not in code.

## Explicitly out of scope in this environment

- Executing any Azure deployment, creating any cloud resource, or incurring cost (no az CLI, no credentials — assumption A1).
- Real manufacturing data, real PII, photorealistic image data.
- Direct machine control of any kind (advisory system only).
