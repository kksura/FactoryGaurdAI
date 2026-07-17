# ADR-0008: Online serving target — FastAPI everywhere, AML endpoint for scoring

Status: Accepted · Date: 2026-07-17

## Context
Serving must behave the same locally and on Azure, return the full prediction contract (explanations, root cause, recommendations), and keep the model-scoring concern replaceable.

## Decision
The **application API** (contract, auth, policy engine, audit) is FastAPI in a container: locally via compose, on Azure via Container Apps. **Model scoring** sits behind a `Scorer` interface: `InProcessScorer` (loads champion from the registry — local default) and `RemoteScorer` (calls an Azure ML **managed online endpoint** — cloud default). Batch scoring mirrors this: local pipeline runner vs AML batch endpoint.

## Alternatives
Everything inside AML endpoints: awkward for the policy/audit/dashboard surface and local dev. Everything in Container Apps incl. models: loses AML's model-deployment features (traffic splitting, safe rollout) that Phase 7 relies on for canary.

## Consequences
One API codebase; swap is a config value; canary/blue-green delegated to AML endpoint traffic splitting in cloud and simulated locally.

## Security considerations
AML endpoint reached via private endpoint with managed-identity auth; the application API is the only ingress; scorer responses are schema-validated (treated as untrusted input).

## Revisit triggers
Latency SLOs that in-process scoring can't meet; multi-model routing needs.
