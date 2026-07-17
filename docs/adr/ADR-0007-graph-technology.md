# ADR-0007: Graph technology — NetworkX features first, optional GNN

Status: Accepted · Date: 2026-07-17

## Context
BOM/routing/supplier/machine/defect relationships form a heterogeneous graph used for root-cause evidence, similarity, and risk features. A GNN is optional per spec; the system must work with it disabled.

## Decision
In-process NetworkX for graph construction and *graph-derived features*: neighbor defect rates with time decay, supplier-lot risk propagation, machine/tool defect centrality, shared-component counts, path-based similarity. Features are computed in the feature pipeline with strict temporal cutoffs (only edges/events before the unit's timestamp). Optional PyG GraphSAGE behind `configs/models/graph.yaml: gnn.enabled=false` — only after the feature baseline passes tests, and skipped entirely if PyG has no working aarch64 install.

## Alternatives
Neo4j/graph database: operational weight, another service to secure; unnecessary at profile scales (≤ millions of edges fit in memory). DGL: heavier ARM64 risk than PyG.

## Consequences
Zero extra infrastructure; graph logic fully unit-testable; GNN is additive, not load-bearing.

## Security considerations
No graph service to expose; graph built from validated Parquet only.

## Revisit triggers
`large`-profile graphs exceeding memory; GNN shows material lift on root-cause metrics.
