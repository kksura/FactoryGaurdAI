# Terraform (partial equivalent — Bicep is the implementation of record)

Per ADR-0013, `infrastructure/bicep/` is authoritative; this directory exists
for organizations standardized on Terraform and intentionally covers only the
**core landing zone**. Anything not covered here must be deployed from the
Bicep modules (or ported following the same settings, property for property).

## Coverage map

| Bicep module | Terraform | Status |
|---|---|---|
| `modules/network.bicep` | `main.tf` (vnet/subnets/NSGs) | ✅ full (minus egress route-table hook) |
| `modules/private-dns.bicep` | `main.tf` (zones + links) | ✅ full |
| `modules/monitoring.bicep` | `main.tf` (LAW + App Insights) | ✅ full |
| `modules/identity.bicep` | `main.tf` (3 UAMIs) | ⚠️ partial — GitHub OIDC federated credentials not ported |
| `modules/keyvault.bicep` | `main.tf` | ✅ full (diagnostics not ported) |
| `modules/storage.bicep` (×2) | `main.tf` | ✅ full (containers/shares/diagnostics not ported) |
| `modules/acr.bicep` | `main.tf` | ✅ full (retention policy/diagnostics not ported) |
| `modules/private-endpoint.bicep` | — | ❌ Bicep only |
| `modules/postgres.bicep` | — | ❌ Bicep only |
| `modules/aml.bicep` | — | ❌ Bicep only |
| `modules/container-apps.bicep` | — | ❌ Bicep only |
| `modules/eventhubs.bicep` | — | ❌ Bicep only |
| `modules/rbac.bicep` | — | ❌ Bicep only |
| `modules/policy.bicep` | — | ❌ Bicep only |
| `modules/budget.bicep` / `lock.bicep` | — | ❌ Bicep only |

## Security notes

- Remote state is a security-sensitive component (one reason Bicep is primary):
  use the `azurerm` backend with `use_azuread_auth = true`, a private,
  versioned, RBAC-restricted state container, and OIDC (`ARM_USE_OIDC=1`) from
  CI — never a service-principal secret.
- The same invariants as Bicep hold: no secrets in code, shared-key access off,
  no public network access, RBAC-only Key Vault.

## Usage

```bash
terraform init -backend-config=backend.hcl     # backend.hcl is org-supplied, not committed
terraform plan -var env=dev -var location=westeurope
```

Authored but not executed in this repository's environment (`terraform init`
requires provider downloads and a backend; recorded in docs/test-evidence.md).
