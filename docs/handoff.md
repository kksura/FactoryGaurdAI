# Handoff Note

Updated 2026-07-19 at the end of the Phase 6 session.
Read this first in a new session, then `PLAN.md` and `docs/implementation-status.md`.

## Current phase

**Phases 0–6 complete and committed. Phase 7 (Azure design + IaC, unexecuted-by-design)
not yet started.**

## What exists and works right now

- Everything from Phases 0–5 (data, training, API, dashboard) plus:
- **MLflow**: `train_multimodal` logs every run — local sqlite by default
  (`sqlite:///mlruns/mlflow.db`, D-034), or `--mlflow-uri http://127.0.0.1:5000`
  against the compose server (verified working, postgres + MinIO backed).
- **Registry**: `factoryguard.mlops.registry.ModelRegistry`
  (`artifacts/registry/`) — gated CANDIDATE→VALIDATED→STAGING→CHAMPION;
  current champion: the small-profile bundle; the API serves it automatically.
- **Observability**: `/metrics` (Prometheus), scraped live by the compose
  Prometheus (`factoryguard-api-host` target, port **8010** on the host — 8000
  is occupied by an unrelated service on this box); Grafana dashboard
  provisioned (`FactoryGuard API`).
- **Drift + retraining**: `python -m pipelines.monitoring.drift_report --profile <p>
  [--simulate-drift]`, then `python -m pipelines.retraining.check_and_retrain
  --profile <p> [--force]`; runbook in `docs/operations/retraining-runbook.md`.
- **Benchmark**: `docs/performance/gb10-benchmark.md` (service P95 56 ms; OI-1/OI-2
  closed).
- **Compose infra stack is currently RUNNING** (postgres/minio/mlflow/prometheus/
  grafana on loopback; `make down` to stop; `.env` holds the generated secrets).
- `.venv/bin/pytest tests/unit tests/ml tests/contract tests/security tests/end_to_end`
  → 172 tests green; ruff + mypy clean (76 files).

## Next task: Phase 7 — Azure (design + code, NOT executed here)

Per `PLAN.md` — everything is IaC/docs only (no credentials, ARM64 workstation):
- Bicep: RG, VNet/subnets, private DNS + endpoints, Key Vault, ADLS/Blob, ACR,
  Log Analytics, App Insights, AML workspace/compute/registry, managed identities,
  RBAC, PostgreSQL, Event Hubs (flag), Container Apps env, budgets, diagnostics
- AML job/environment/endpoint YAML; batch endpoint
- Foundry integration doc; optional Fable 5 summarizer wiring (ADR-0015 rules)
- Architecture docs + Mermaid diagrams; port/protocol + identity matrices
- Deployment/rollback runbooks; teardown scripts
- Mark actual deployment as blocked on subscription/credentials/cost approval

## Things NOT to re-litigate

- All Phase 4/5 decisions (D-028/D-030/D-032/D-033) still stand.
- MLflow local = sqlite (D-034); plain file store raises in mlflow 3.14.
- Registry gates are code we own (`configs/policies/promotion.yaml`); MLflow
  tracks experiments, the registry tracks deployables — don't merge them.
- Breach rule excludes consumable-lot ids (D-036) — their churn is expected.
- `/metrics` anonymity is a documented, gated exception (D-037).
- Drift-aware anomaly weights exist but default OFF (ADR-0019 baseline rule).

## Gotchas that still matter

1. Postgres container must keep `user: postgres` (D-035) — cap_drop ALL breaks
   the image's own privilege drop otherwise.
2. Port 8000 on this box belongs to another project — serve on 8010 for the
   Prometheus host target; never kill the foreign listener.
3. `pkill -f` with a pattern that appears in your own shell command kills the
   shell (exit 144) — match on exact PIDs instead.
4. Artifact write order stays lineage → manifest (D-031); `.gitignore` anchoring;
   bounded time-features (D-024); `row["shift"]` not `row.shift`.
5. api/dashboard container images are unbuilt (OI-9) — expect a very long first
   build (torch layers) if attempted.
6. OTLP exporter is not pinned: tracing works with the console exporter locally;
   collector wiring belongs to Phase 7.

## Environment facts (verified, don't re-verify)

- GB10, ARM64, CUDA 13.0, torch 2.9.1+cu130 — benchmarked ×25 GPU speedup (OI-1
  closed). No Azure CLI/credentials — Phase 7 stays unexecuted-by-design.
- `.env` exists with generated secrets (gitignored); FG_AUTH__LOCAL_JWT_SECRET
  is set there for `make serve` and the token script.

## Working-memory files to update every phase

`PLAN.md`, `docs/implementation-status.md`, `docs/decision-log.md`,
`docs/open-issues.md`, `docs/test-evidence.md`, this file.
