# ADR-0013: Infrastructure as code — Bicep primary

Status: Accepted · Date: 2026-07-17

## Context
Azure-only target (Foundry, AML, Container Apps, private networking). Spec allows Terraform or Bicep with the other optional.

## Decision
**Bicep** is the implementation of record (`infrastructure/bicep/` — modules + per-environment parameter files). Rationale: first-class Azure resource coverage on day one (AML managed network, Foundry projects), no state file to store/secure (deployments are incremental against ARM), native what-if for plan-only CI, az-CLI-only toolchain. A **partial Terraform equivalent** for the core landing zone lives in `infrastructure/terraform/` with a README mapping module-for-module, for orgs standardized on Terraform.

## Alternatives
Terraform primary: excellent, but remote state adds a security-sensitive component and new Azure features lag in the provider; multi-cloud portability is not a requirement here.

## Consequences
Plan-only CI uses `az deployment what-if`; linting via `bicep build` + PSRule-style checks (documented). In this offline environment, `bicep build` runs via container if available — otherwise templates are marked lint-unverified in test evidence.

## Security considerations
No secrets in parameters (Key Vault references only); deletion locks on prod resources; deployment identities scoped per environment via workload identity federation.

## Revisit triggers
Org mandates Terraform; multi-cloud scope appears.
