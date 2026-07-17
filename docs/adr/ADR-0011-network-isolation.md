# ADR-0011: Network isolation

Status: Accepted · Date: 2026-07-17

## Context
Zero-trust requirement: no public endpoints by default, controlled egress, private access to data/ML services.

## Decision
- **Local**: every service binds `127.0.0.1` only; compose network is internal; no published ports beyond loopback.
- **Azure**: spoke VNet with dedicated subnets (container-apps environment, private-endpoints, AML managed network). Public network access disabled on storage, Key Vault, ACR, AML workspace, PostgreSQL; access via private endpoints + private DNS zones. AML workspace uses managed network isolation (allow-only-approved-outbound). Container Apps ingress internal; any external exposure goes through Application Gateway + WAF as a deliberate, documented exception. Egress via hub firewall (assumption A11). No public SSH/RDP anywhere; admin path is Azure Bastion in the hub.

## Alternatives
Service firewalls/IP allow-lists without private endpoints: weaker, leaves public DNS surface. Fully isolated air-gap: breaks AML/Foundry management planes.

## Consequences
IaC must provision private DNS zones per service (blob, dfs, vault, acr, aml api/notebooks, postgres); CI agents need network line-of-sight (documented: self-hosted runner in VNet or temporary approved exceptions for deploy).

## Security considerations
This is the primary containment control for data exfiltration and lateral movement; paired with deny-by-default NSGs and diagnostic logging to Log Analytics.

## Revisit triggers
Multi-region DR design; Front Door adoption; partner-facing API requirements.
