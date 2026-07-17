# ADR-0009: Azure ML + Container Apps, not AKS

Status: Accepted · Date: 2026-07-17

## Context
Cloud runtime choice for training, model serving, API, workers, dashboard. Working principle: least operationally complex service that satisfies requirements.

## Decision
- Training/experiments/registry/model endpoints: **Azure Machine Learning** (compute clusters, managed online + batch endpoints, MLflow tracking) inside a managed-network workspace.
- Application API, monitoring worker, dashboard: **Azure Container Apps** (internal ingress, VNet-integrated environment, KEDA scaling, managed identity).
- **AKS is explicitly not adopted now.** Trigger criteria documented below.

## Alternatives
AKS for everything: maximal control, but node management, upgrade cadence, and cluster security hardening are unjustified for a handful of stateless services. App Service: weaker container/worker story than Container Apps.

## Consequences
No cluster to operate; per-service scaling; AML handles GPU pools and safe rollout. Some Container Apps limits (no privileged daemonsets — irrelevant here).

## Security considerations
Both services support managed identity, VNet integration, and private ingress; smaller attack/ops surface than a self-managed cluster.

## Revisit triggers (AKS criteria)
Need for custom GPU serving stacks (Triton at scale), service mesh requirements, >~20 microservices, cross-workload bin-packing economics, or org-mandated AKS landing zone.
