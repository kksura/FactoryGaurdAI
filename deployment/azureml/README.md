# Azure ML assets (authored, NOT executed — Phase 7)

Everything the AML side of the deployment needs, driven with `az ml` from an
authorized operator workstation or the release pipeline (never from the GB10 —
spec §13). `<...>` placeholders are filled per-org; `scripts/azure/deploy.sh`
refuses to run while any remain.

| Asset | File | Notes |
|---|---|---|
| Training environment | `environments/train-env.yaml` | prebuilt ACR image, deps + weights baked at build (no run-time egress) |
| Serving environment | `environments/serve-env.yaml` | slim scoring image |
| Curated datastore | `datastores/datalake-curated.yaml` | identity-based ADLS Gen2, no keys |
| Training job | `jobs/train-multimodal.yaml` | same CLI as `make train-multimodal`; MLflow to the workspace |
| Online endpoint | `endpoints/online-endpoint.yaml` | `aad_token` auth, private only |
| Online deployment | `endpoints/online-deployment-blue.yaml` | blue/green + traffic shifting for canary |
| Batch endpoint | `endpoints/batch-endpoint.yaml` + `endpoints/batch-deployment.yaml` | JSONL in/out, fail-loud |
| Scoring entries | `scoring/score.py`, `scoring/score_batch.py` | thin adapters over the tested `PredictionService` |

## Order of operations

```bash
az ml datastore create -f datastores/datalake-curated.yaml
az ml environment create -f environments/train-env.yaml
az ml environment create -f environments/serve-env.yaml
az ml job create -f jobs/train-multimodal.yaml --set inputs.profile=small
# … registry promotion happens via pipelines/registration (human-gated) …
az ml online-endpoint create -f endpoints/online-endpoint.yaml
az ml online-deployment create -f endpoints/online-deployment-blue.yaml --all-traffic
az ml batch-endpoint create -f endpoints/batch-endpoint.yaml
az ml batch-deployment create -f endpoints/batch-deployment.yaml --set-default
```

Traffic shifting / rollback commands live in
`docs/operations/azure-deployment-runbook.md` §7.
