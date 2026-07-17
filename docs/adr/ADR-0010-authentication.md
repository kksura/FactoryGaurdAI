# ADR-0010: Authentication and authorization

Status: Accepted · Date: 2026-07-17

## Context
API needs authN/Z locally (no cloud IdP available) and Entra ID in Azure, with identical role/scope semantics, deny-by-default.

## Decision
A `TokenVerifier` interface with:
- **LocalJwtVerifier** (dev/test only): HS256 JWTs issued by `scripts/issue_dev_token.py` using a secret from `.env`. Config validation forbids this provider in staging/production.
- **EntraIdVerifier** (cloud): OIDC discovery, JWKS-cached RS256 validation, audience `api://factoryguard`, tenant-pinned issuer.

Claims map to roles: `platform-admin`, `ml-engineer`, `data-steward`, `quality-engineer`, `plant-viewer`, `auditor`, `service`. Every route declares required scopes via dependency; no route is anonymous except `/health/*` and `/version`. Managed identities/workload identity federation are used service-to-service in Azure (no client secrets).

## Alternatives
API keys: no identity, weak rotation story — rejected. Full local Keycloak: heavy for a dev loop; the dev issuer is 50 lines and structurally identical to production verification.

## Consequences
Same authorization tests run against both providers; production cannot boot with the dev provider (fail-closed config).

## Security considerations
Short TTL tokens, audience+issuer pinning, clock-skew bounds, JWKS cache with kid rotation, authorization decisions logged (identity, route, decision) without token contents.

## Revisit triggers
Entra ID group-to-role mapping requirements; fine-grained per-plant authorization needs.
