# Tutorial source map

Evidence index for `FACTORYGUARD-COMPLETE-TUTORIAL.md`. Every chapter lists the
repository files inspected while writing it. Generated at commit `700f5ad`
(Phase 7 complete), 2026-07-19. Where a chapter makes claims about executed
results (test counts, benchmark numbers, metric values), the claim traces to
`docs/test-evidence.md` or to a committed report/metrics file — never to the
specification alone.

| Chapter | Primary evidence files |
|---|---|
| Title / status | `PLAN.md`, `docs/implementation-status.md`, `git log` (9 phase commits, `789ff51`…`700f5ad`) |
| 1 What FactoryGuard is | `README.md`, `docs/specification/factoryguard-spec-v2.md` §1–4, `src/factoryguard/contracts/v1.py` |
| 2 Manufacturing domain | `src/factoryguard/data/world.py`, `data/mechanisms.py`, `configs/data/tiny.yaml` |
| 3 Big-picture architecture | `docs/architecture/local-architecture.md`, `docs/architecture/azure-architecture.md`, `docs/architecture/data-flow.md` |
| 4 Environment / GB10 | `docs/environment-assessment.md`, `docs/performance/gb10-benchmark.md`, `scripts/doctor.py`, `docs/test-evidence.md` |
| 5 Repository tour | repository tree, `pyproject.toml`, `Makefile`, `docs/implementation-plan.md` |
| 6 Configuration | `src/factoryguard/config/settings.py`, `configs/environments/*.yaml`, `configs/policies/*.yaml`, `configs/data/*.yaml`, `configs/models/multimodal.yaml` |
| 7 Synthetic data | `src/factoryguard/data/{world,mechanisms,units,timeseries,images,graphdata,generate,profiles}.py`, `pipelines/data/generate.py`, D-024 in `docs/decision-log.md` |
| 8 Validation & contracts | `src/factoryguard/data/validation.py`, `src/factoryguard/contracts/v1.py`, `tests/contract/`, `pipelines/data/validate.py` |
| 9 Feature engineering | `src/factoryguard/features/{tabular,graph}.py`, `src/factoryguard/evaluation/splits.py`, D-024/D-032 |
| 10 ML fundamentals | `src/factoryguard/evaluation/splits.py`, `configs/data/tiny.yaml` (label delay, prevalence) |
| 11 Tabular models | `src/factoryguard/models/tabular/{rule_baseline,sklearn_models,tabpfn_challenger}.py`, D-025, OI-5 |
| 12 Time series | `src/factoryguard/models/timeseries/{stat_detector,cnn_encoder}.py`, D-029 |
| 13 Vision / DINOv2 | `src/factoryguard/models/vision/{dinov2,attribution,quality}.py` (pinned SHA-256 at `dinov2.py:33`), ADR-0018, D-027 |
| 14 Graph features | `src/factoryguard/features/graph.py`, `src/factoryguard/data/graphdata.py`, ADR-0007, D-032 |
| 15 Fusion | `src/factoryguard/models/fusion/{late,embedding,inputs}.py`, ADR-0006 |
| 16 Serving modes | `src/factoryguard/inference/serving.py`, ADR-0019, OI-7, `monitoring/drift.py` (drift-aware weights) |
| 17 Calibration/uncertainty | `src/factoryguard/models/calibration/scaling.py`, `src/factoryguard/inference/uncertainty.py`, D-028, `reports/evaluation/small/multimodal-metrics.json` |
| 18 Evaluation | `src/factoryguard/evaluation/{splits,metrics}.py`, `tests/ml/test_splits.py`, `configs/policies/promotion.yaml` (Scenario G gates) |
| 19 Explainability | `src/factoryguard/explainability/root_cause.py`, `src/factoryguard/models/vision/attribution.py`, `src/factoryguard/inference/retrieval.py`, D-030 |
| 20 Recommendations | `src/factoryguard/recommendations/{engine,audit}.py` (ACTION_TAXONOMY lines 28–40, POL-001..008), ADR-0017 |
| 21 Assistants | `src/factoryguard/assistants/summarizer.py`, ADR-0020, D-033/D-041, `tests/unit/test_assistant.py` |
| 22 API | `src/factoryguard/api/{routes,middleware,app,deps,metrics}.py`, `apps/api/main.py`, `tests/end_to_end/test_api_flow.py` |
| 23 AuthN/AuthZ | `src/factoryguard/auth/verifier.py`, ADR-0010, `configs/environments/production.yaml`, `scripts/issue_dev_token.py` |
| 24 Dashboard | `apps/dashboard/main.py` (4 tabs), `tests/end_to_end/test_dashboard.py` |
| 25 Tracking & registry | `src/factoryguard/mlops/{tracking,registry}.py`, `configs/policies/promotion.yaml`, ADR-0004/0005, D-034 |
| 26 Monitoring | `src/factoryguard/api/metrics.py`, `src/factoryguard/utilities/{logging,tracing}.py`, `infrastructure/compose/prometheus.yml`, grafana provisioning, D-037 |
| 27 Drift & retraining | `src/factoryguard/monitoring/drift.py`, `pipelines/retraining/check_and_retrain.py`, `configs/policies/drift.yaml`, D-036, ADR-0016 |
| 28 Security architecture | `docs/architecture/security-architecture.md`, `SECURITY.md`, `src/factoryguard/api/middleware.py`, `src/factoryguard/security/*` (threat model **absent** — Phase 8) |
| 29 Supply chain | `requirements/lock.txt`, `.pre-commit-config.yaml`, `.github/workflows/pr.yml`, `scripts/{sbom,scan}.sh`, ADR-0012, `Dockerfile` |
| 30 Containers | `Dockerfile`, `docker-compose.yml`, `infrastructure/compose/*`, D-035, OI-9 |
| 31 Testing | `tests/` tree (182 collected at this commit), `pyproject.toml` pytest config, `docs/test-evidence.md` |
| 32 CI/CD | `.github/workflows/pr.yml` (jobs: quality, supply-chain, container — authored, unexecuted OI-4), ADR-0014, `docs/operations/azure-devops-equivalents.md` |
| 33 IaC | `infrastructure/bicep/**` (main + 15 modules + params + README), `infrastructure/terraform/**`, ADR-0013, test evidence (bicep build 0 warnings) |
| 34 Azure architecture | `docs/architecture/{azure-architecture,network-topology,data-flow,security-architecture}.md`, all Bicep modules |
| 35 AML workflow | `deployment/azureml/**`, `docs/operations/azure-deployment-runbook.md`, `deployment/azureml/scoring/*.py`, `tests/unit/test_azureml_scoring.py` |
| 36 Foundry | `docs/operations/foundry-integration.md`, `src/factoryguard/assistants/summarizer.py` (FoundrySummarizer), ADR-0015, OI-11 |
| 37 Container Apps | `infrastructure/bicep/modules/container-apps.bicep`, ADR-0009 |
| 38 Azure security | `docs/architecture/security-architecture.md` (identity matrix), `infrastructure/bicep/modules/{identity,rbac}.bicep`, `docs/architecture/network-topology.md` (port matrix) |
| 39 Deploy & rollback | `scripts/azure/{deploy,teardown}.sh`, `docs/operations/azure-deployment-runbook.md`, `docs/operations/retraining-runbook.md`, `Makefile` |
| 40 Scenarios A–J | spec v2 §28, `configs/data/*.yaml` mechanisms, `tests/ml/`, `tests/unit/test_image_quality.py`, OI-7 |
| 41 Troubleshooting | `scripts/doctor.py`, `docs/test-evidence.md`, OI-1..OI-11, D-035 |
| 42 Extension guide | `src/factoryguard/contracts/v1.py` (additive-only tests), `configs/`, `tests/contract/` |
| 43 Exercises | `Makefile`, `pipelines/`, generated `data/` layout |
| 44 FAQ | ADRs 0001–0021, `docs/open-issues.md`, decision log |
| 45 Status | `PLAN.md` acceptance tracker, `docs/implementation-status.md`, `docs/open-issues.md`, `docs/test-evidence.md` |
| 46 Learning paths | tutorial chapter structure (internal) |
| 47 Glossary | terms as used across the above sources |
| 48 Reference | `Makefile`, repo tree, `configs/`, `docs/adr/` index |
| App. A–L | same sources; App. G from Bicep modules; App. H from `docs/adr/ADR-0001..0021`; App. J from spec §31 + `PLAN.md` tracker; App. K from `git log` |

Known evidence gaps carried into the tutorial as explicit status labels:

- `docs/security/` and `docs/responsible-ai/` are **empty** — threat model and
  responsible-AI doc set are Phase 8 (`PLAN.md`); dataset cards exist per
  generated dataset, and a model card is generated as an MLflow artifact
  (Phase 6), but no standing RAI documents exist yet.
- `FINAL-REPORT.md` does not exist (Phase 8).
- `pipelines/{deployment,evaluation,registration}/` are empty directories;
  registration/promotion logic lives in `src/factoryguard/mlops/registry.py`
  and `pipelines/retraining/check_and_retrain.py`.
- `apps/worker/` contains only `__init__.py` — the drift/monitoring worker
  runs via `pipelines/monitoring/drift_report.py` and
  `pipelines/retraining/check_and_retrain.py`, not a standing daemon.
- GitHub Actions authored but never executed (no remote, OI-4); Azure
  templates lint-validated only (OI-10); `anthropic` SDK not pinned (OI-11).
