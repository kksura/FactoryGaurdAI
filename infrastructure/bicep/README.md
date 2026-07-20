# FactoryGuard AI — Bicep infrastructure

Bicep is the IaC implementation of record (ADR-0013); a partial Terraform
equivalent lives in `../terraform/`. **Nothing here deploys from the GB10
development environment** — execution requires a subscription, credentials,
region, and cost approval (spec §13), and goes through
`scripts/azure/deploy.sh` or the CI pipeline (plan-only `what-if` on PR,
gated `create` on release; ADR-0014).

## Layout

| File | Scope | Contents |
|---|---|---|
| `main.bicep` | subscription | resource group, budget + cost alerts, delete lock, hand-off to `stack.bicep` |
| `stack.bicep` | resource group | orchestrates every module below, incl. all private endpoints |
| `modules/network.bicep` | RG | spoke VNet, container-apps + private-endpoints subnets, deny-by-default NSGs |
| `modules/private-dns.bicep` | RG | one private DNS zone per private-link service, linked to the VNet |
| `modules/private-endpoint.bicep` | RG | reusable PE + DNS zone group |
| `modules/monitoring.bicep` | RG | Log Analytics + workspace-based App Insights (Entra-only ingestion) |
| `modules/identity.bicep` | RG | runtime / training / deploy user-assigned identities, GitHub OIDC federation |
| `modules/keyvault.bicep` | RG | RBAC-only Key Vault, purge protection, private access |
| `modules/storage.bicep` | RG | generic account — instantiated as ADLS Gen2 data lake and blob artifacts/AML-default; shared keys disabled |
| `modules/acr.bicep` | RG | Premium ACR, admin user off, export policy off |
| `modules/postgres.bicep` | RG | PostgreSQL Flexible 16, Entra-only auth (no passwords exist), private endpoint access |
| `modules/aml.bicep` | RG | AML workspace (managed network, approved-outbound-only), CPU (+optional GPU) clusters, model registry |
| `modules/eventhubs.bicep` | RG | flag-gated Event Hubs namespace (streaming is off by default, ADR-0021) |
| `modules/container-apps.bicep` | RG | internal Container Apps environment + api/dashboard/worker apps |
| `modules/rbac.bicep` | RG | every role assignment, resource-scoped; mirrors the identity matrix doc |
| `modules/policy.bicep` | RG | guardrail policy assignments (deny public network etc.) |
| `modules/budget.bicep` | subscription | monthly budget filtered to the spoke RG |
| `modules/lock.bicep` | RG | CanNotDelete lock (prod) |
| `environments/*.bicepparam` | — | dev / prod parameter files; `<...>` placeholders must be replaced |

## Usage (from an authorized operator workstation or CI)

```bash
az deployment sub what-if --location westeurope \
  --template-file infrastructure/bicep/main.bicep \
  --parameters infrastructure/bicep/environments/dev.bicepparam

az deployment sub create --location westeurope \
  --template-file infrastructure/bicep/main.bicep \
  --parameters infrastructure/bicep/environments/dev.bicepparam
```

See `docs/operations/azure-deployment-runbook.md` for the full ordered
procedure (auth → subscription → what-if → deploy → data upload → AML jobs →
endpoints → smoke tests) and rollback.

## Design invariants

- **No secrets in templates or parameters** — PostgreSQL is Entra-only (password
  auth disabled), storage has shared-key access off, ACR admin user off,
  Event Hubs local auth off. Anything secret-shaped lives in Key Vault and is
  read at runtime by managed identity.
- **No public network access** on storage, Key Vault, ACR, AML, PostgreSQL,
  Event Hubs; Container Apps ingress is internal. External exposure would be a
  deliberate App Gateway + WAF exception (ADR-0011), not part of this stack.
- **Diagnostics to Log Analytics** on every service that supports it.
- **Policy assignments** audit (dev) or enforce (prod) the same invariants so
  drift via portal edits is caught.
- Templates are validated locally with `bicep build` (see
  `docs/test-evidence.md`); `what-if` against a real subscription is the CI
  plan step and has not been executed from this environment.
