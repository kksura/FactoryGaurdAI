# Azure deployment + rollback runbook (Phase 7 — authored, unexecuted)

Ordered procedure implementing spec §24. **Preconditions before step 1:**
subscription id, region, cost approval for the environment's budget, an Entra
admin *group* for PostgreSQL, and (for CI) a GitHub repository with
environments `dev`/`production` configured with required reviewers. Nothing
here runs from the GB10 development environment.

## 1. Authenticate and select subscription

Operator: `az login` (+ `az account set`). CI: OIDC workload identity
federation only — no stored credentials (ADR-0014). The federated credential
is created by `identity.bicep` once `githubRepository` is set, which gives a
bootstrap ordering: the **first** deployment of an environment is run by a
human subscription owner; every later one can run through CI with the deploy
UAMI.

## 2. One-time pipeline grants (subscription owner)

- Deploy UAMI: `Contributor` scoped to `rg-fg-<env>` **after** first deploy,
  plus subscription-scope `Reader` for what-if. Subscription-level RG/budget
  creation stays with the human owner path.
- Record both grants in the change log; they are deliberately not in
  rbac.bicep (see `security-architecture.md`).

## 3. Fill parameters

Copy real org values over every `<placeholder>` in
`infrastructure/bicep/environments/<env>.bicepparam` (tenant id, Entra group,
alert emails, GitHub repo, budget start date = first of current month, prod:
image digests + GPU size from the benchmark). `deploy.sh` hard-fails while
any placeholder remains.

## 4. Plan, then deploy infrastructure

```bash
AZ_SUBSCRIPTION=<sub-id> scripts/azure/deploy.sh dev plan    # what-if, safe
AZ_SUBSCRIPTION=<sub-id> scripts/azure/deploy.sh dev apply   # gated apply
```

Review the what-if diff — expected on first run: 1 RG, VNet+2 NSGs, 9 DNS
zones, LAW+AppInsights, 3 UAMIs, KV, 2 storage accounts, ACR, PG flexible
server, AML workspace+cpu-cluster+registry, CAE + 3 container apps, ~9
private endpoints, policy assignments, budget. Anything *deleted* on a later
run needs explanation before apply.

## 5. Publish images

CI (or operator with AcrPush) builds from the repo Dockerfile targets and
pushes `factoryguard/{api,dashboard,worker,train,serve}`. Record digests;
update the prod parameter file with them (digest pinning, spec §14). Note
OI-9: the api image has never been built — expect a long first build
(multi-GB torch layers) and do it on an amd64 builder matching the cloud CPU
target, not the ARM64 GB10.

## 6. Data + AML assets + training

```bash
# upload a generated dataset (from a machine with data + network line-of-sight)
az storage blob upload-batch --auth-mode login \
  --account-name <datalake> -d curated/datasets/small -s data/small

cd deployment/azureml
az ml datastore create -f datastores/datalake-curated.yaml
az ml environment create -f environments/train-env.yaml
az ml environment create -f environments/serve-env.yaml
az ml job create -f jobs/train-multimodal.yaml --set inputs.profile=small
```

Verify in the workspace: job completed, MLflow run has lineage tags, output
`artifacts/` contains a manifest-verified bundle, evaluation report meets the
promotion floors in `configs/policies/promotion.yaml`.

## 7. Register, deploy endpoints, canary

```bash
az ml model create --name factoryguard-multimodal --path <job-output-artifacts>
# registry promotion (CANDIDATE→VALIDATED→STAGING) runs via pipelines/registration
# with the human approval gate (ADR-0017) — no promotion without an approver.

az ml online-endpoint create -f endpoints/online-endpoint.yaml
az ml online-deployment create -f endpoints/online-deployment-blue.yaml --all-traffic
az ml batch-endpoint create -f endpoints/batch-endpoint.yaml
az ml batch-deployment create -f endpoints/batch-deployment.yaml --set-default
```

**Smoke tests** (from a VNet-internal runner): `GET /health/ready` on the api
app; one authenticated `POST /api/v1/predictions` with a known unit; assert
schema-valid response, `serving_mode`, audit-verify OK.

**Canary for a new model version (green):**

```bash
az ml online-deployment create -f endpoints/online-deployment-blue.yaml \
  --set name=green model=azureml:factoryguard-multimodal:<new-version>
az ml online-endpoint update -n fg-scoring --traffic "blue=90 green=10"
# gate check → 50/50 → gate check → 0/100; delete blue only after soak
```

Gate checks between steps (App Insights + drift suite): P95 latency within
budget, error rate < 1%, abstention rate within ±5pp of blue, no calibration
drift alert. Any breach → rollback (below). This implements demonstration
scenario G's operational half: a candidate that fails gates never takes
traffic.

## 8. Rollback

| Layer | Action | Time |
|---|---|---|
| Model (canary) | `az ml online-endpoint update -n fg-scoring --traffic "blue=100 green=0"` | seconds |
| Model (post-promotion) | registry: demote champion → previous VALIDATED (`pipelines/registration` rollback path, audited); redeploy blue with prior version | minutes |
| Application | Container Apps keeps prior revisions: `az containerapp revision activate` + route 100% to previous revision | seconds–minutes |
| Infrastructure | redeploy the last known-good git tag of `infrastructure/bicep` (deployments are incremental; state = ARM) | minutes |
| Data | PostgreSQL PITR (14-day window; geo-backup in prod); storage soft delete 14 days | minutes–hours |

Every rollback writes an entry to the audit log with the approver identity —
the same requirement as promotion.

## 9. Teardown

Non-prod: `scripts/azure/teardown.sh dev` (interactive confirmation; refuses
prod). Prod decommission is a change-managed procedure: export audit logs +
final backups → sign-off → remove the CanNotDelete lock → delete RG → verify
budget closure. Key Vault purge protection means vault names stay reserved
for the soft-delete window — this is intended.

## 10. Cost guardrails

Budgets deploy with the stack (80%/100% actual, 110% forecast alerts to the
ops + finops aliases). First response to a cost alert: check AML compute
(`min_nodes` must be 0), Container Apps replica counts, and Log Analytics
ingestion (`dailyQuotaGb` in dev). The GPU cluster is the single most
expensive optional component — it exists only if `gpuClusterVmSize` is set.
