# FactoryGuard AI

Multimodal machine-learning platform that predicts wire-harness manufacturing quality defects **before** end-of-line inspection — fusing tabular process data, machine time-series, inspection images, and product/process graph relationships into calibrated, explainable, policy-governed risk predictions.

> Advisory system. It recommends containment/investigation actions; it never controls machinery, and high-impact recommendations require human approval.

## Status

Under active construction — see `PLAN.md` for the phase checklist and `docs/implementation-status.md` for truthful current state. Local target: NVIDIA GB10 (ARM64, CUDA 13). Cloud target: Azure (Microsoft Foundry + Azure ML) — infrastructure is code + docs only until credentials/cost approval exist.

## Quick start (local)

```bash
make setup            # create venv, install pinned deps
make doctor           # verify Python/GPU/CUDA/deps health
make generate-data PROFILE=small
make validate-data
make train-baseline
make serve            # API on http://127.0.0.1:8000
make test
```

Full stack (PostgreSQL, MinIO, MLflow, Prometheus, Grafana, API, dashboard):

```bash
make up
make down
```

Each quick-start command is validated in `docs/test-evidence.md` as it becomes available; commands not yet implemented fail loudly rather than pretending.

## Repository map

See `docs/implementation-plan.md` for the annotated tree. Highlights: `src/factoryguard/` (library code), `pipelines/` (runnable stages), `configs/` (data profiles, model configs, policies, environments), `infrastructure/` (Bicep primary IaC + compose), `docs/` (architecture, security, operations, responsible AI), `tests/` (unit/integration/contract/security/performance/ml/e2e).

## Security & responsible AI

- `SECURITY.md` — policy and design commitments.
- `docs/security/` — threat model, security architecture.
- `docs/responsible-ai/` — model card, dataset card, limitations, impact assessment. Synthetic data only; pseudonymous operators; **no individual-worker scoring**.
