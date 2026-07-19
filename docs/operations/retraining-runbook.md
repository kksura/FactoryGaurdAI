# Retraining Runbook (spec §21/§24)

## Automated part (`pipelines.retraining.check_and_retrain`)

1. `python -m pipelines.monitoring.drift_report --profile <p>` — refresh drift state.
2. `python -m pipelines.retraining.check_and_retrain --profile <p>` — applies the
   sustained-breach rule (`configs/policies/drift.yaml`); on breach trains a
   candidate into `artifacts/candidates/<timestamp>/`, registers it, records the
   champion comparison, and attempts VALIDATED promotion through the metric gates
   (`configs/policies/promotion.yaml`). Decision file:
   `reports/retraining/<p>/decision.json`.

Nothing beyond VALIDATED is automated — by design (ADR-0017).

## Human part (promotion to CHAMPION)

```python
from pathlib import Path
from factoryguard.mlops.registry import ModelRegistry

reg = ModelRegistry(Path("artifacts/registry"))
reg.promote(model_id, "STAGING", actor="<you>")          # manifest re-verified
reg.approve(model_id, actor="<you>", actor_roles=["ml-engineer"])
reg.promote(model_id, "CHAMPION", actor="<you>")         # requires approval +
                                                         # recorded comparison
```

The API serves the registry champion automatically on next start
(`model.serving_alias: champion`); the previous champion is archived, so
rollback = re-promote the archived entry via a fresh CANDIDATE registration of
its artifact directory (its manifest still verifies).

## Shadow / canary (design; execution needs a second API instance)

- **Shadow**: run a second `PredictionService` on the candidate bundle behind the
  same requests, log to `artifacts/serving-logs/shadow-*.jsonl`, compare score
  distributions + abstention rates before approval. The service class already
  supports side-by-side instantiation (no globals).
- **Canary**: route a fixed percentage of traffic by `Idempotency-Key` hash at
  the gateway (Azure Front Door in the Phase 7 design). Locally, shadow mode is
  the supported rehearsal; full canary needs the cloud gateway.

## Audit trail

Every register/approve/promote lands in the hash-chained
`artifacts/registry/registry-audit.jsonl` (`AuditLog.verify()` detects tamper),
alongside the per-model `history` in `registry.json`.
