# ADR-0014: CI/CD identity — GitHub Actions with workload identity federation

Status: Accepted · Date: 2026-07-17

## Context
Pipelines must authenticate to Azure without stored cloud credentials.

## Decision
GitHub Actions using **OIDC workload identity federation**: per-environment Entra ID app registrations / user-assigned managed identities with federated credentials scoped to repo+branch+environment (`environment: production` requires reviewers). Roles assigned least-privilege per pipeline stage (plan: Reader + what-if; deploy: scoped Contributor on the spoke RG; AML ops: AzureML Data Scientist/Registry User). No PATs, no service-principal secrets in GitHub secrets. Azure DevOps equivalent (service connections with workload identity federation) documented in `docs/operations/azure-devops-equivalents.md`.

## Alternatives
SP client secrets: rotation burden + exfiltration risk — rejected by spec. Self-hosted runner with managed identity: viable for VNet-internal deploys; documented as the private-network option.

## Consequences
Zero long-lived cloud secrets in CI; branch protection becomes part of the security boundary.

## Security considerations
Federated credential subject filters pinned exactly; production environment gates require human approval, satisfying the promotion-approval requirement end-to-end.

## Revisit triggers
Move to Azure DevOps; need for cross-tenant deployments.
