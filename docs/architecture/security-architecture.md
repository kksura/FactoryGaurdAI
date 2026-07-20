# Security architecture (Azure target)

Zero-trust posture from spec §14: no public endpoints (ADR-0011), no shared
credentials anywhere, deny-by-default authorization at every layer, fail-closed
configuration (`_fail_closed` refuses to start hardened environments with any
insecure combination — implemented and tested in Phase 1).

## Identities

| Identity | Kind | Used by | Created in |
|---|---|---|---|
| `id-fg-<env>-runtime` | UAMI | Container Apps api/dashboard/worker | `identity.bicep` |
| `id-fg-<env>-training` | UAMI | AML compute clusters | `identity.bicep` |
| `id-fg-<env>-deploy` | UAMI + GitHub OIDC federation | CI/CD pipelines (ADR-0014) | `identity.bicep` |
| AML workspace MSI | system-assigned | workspace-managed operations | `aml.bicep` |
| AML endpoint MSI | system-assigned | online endpoint scoring identity | endpoint YAML |
| Human roles | Entra users/groups | API access (7-role model), approvals, Entra PG admin group | org directory |

No service principals with client secrets exist anywhere. CI reaches Azure
exclusively through workload identity federation with the subject pinned to
`repo:<owner>/<repo>:environment:<env>` — a run acquires the deploy identity
only after that GitHub environment's required reviewers approve (ADR-0014).

## Identity → resource access matrix

Mirrors `infrastructure/bicep/modules/rbac.bicep` — change them together.
Every assignment is scoped to the individual resource, never the subscription.

| Identity | Resource | Role | Why |
|---|---|---|---|
| runtime | ACR | AcrPull | pull app images |
| runtime | Key Vault | Key Vault Secrets User | read runtime secrets (e.g. Foundry key) |
| runtime | Blob artifacts | Storage Blob Data Contributor | read model bundles, write prediction/feedback logs |
| runtime | ADLS data lake | Storage Blob Data Reader | read curated reference data |
| runtime | resource group | Monitoring Metrics Publisher | push custom metrics |
| training | ADLS data lake | Storage Blob Data Contributor | read datasets, write derived data |
| training | Blob artifacts | Storage Blob Data Contributor | write model bundles + reports |
| training | ACR | AcrPull | pull the training image |
| training | Key Vault | Key Vault Secrets User | optional tokens (e.g. TabPFN) |
| deploy | ACR | AcrPush | publish images from CI |
| deploy | AML workspace | AzureML Data Scientist | submit jobs, register models, manage endpoints |
| deploy | resource group | Reader | what-if / plan |
| workspace MSI | Blob artifacts | Storage Blob Data Contributor + Storage File Data Privileged Contributor | identity-mode system datastores (shared keys are off) |
| workspace MSI | ACR | AcrPull | environment images for jobs/endpoints |

Infra deploys (the `az deployment sub create` itself) need a broader grant —
scoped Contributor on the spoke RG plus the subscription-level rights for RG/
budget creation. That grant is applied at pipeline setup by a subscription
owner and documented in the runbook §2; it is deliberately **not** baked into
rbac.bicep to keep the elevated path a conscious, auditable step.

## API authorization (implemented, Phase 5)

Seven roles (platform-admin, ml-engineer, data-steward, quality-engineer,
plant-viewer, auditor, service) map to scopes; **every** route is deny-by-
default. Cloud tokens come from Entra (issuer/audience pinned in config;
`EntraIdVerifier`), dev tokens from the local-JWT provider which the
fail-closed config **refuses to start** in hardened environments. Request
hardening: body-size limit 413, content-type allow-list 415, fixed-window
rate limit 429, security headers, correlation ids, idempotency keys, safe
uniform errors.

## Secrets and keys

- **Key Vault only** — RBAC-authorization mode, purge protection, private
  endpoint. Bicep templates contain no secret material by construction:
  PostgreSQL has password auth *disabled* (Entra-only), storage has shared
  keys *disabled*, ACR admin user off, Event Hubs local auth off, App
  Insights Entra-only ingestion.
- Rotation: the only long-lived secret in the whole design is the optional
  Foundry API key (rotate via Key Vault versioning; consumers read at
  startup). Everything else is a short-lived Entra token by design.
- **Encryption**: TLS ≥1.2 everywhere in transit; platform-managed keys at
  rest. High-assurance option: CMK via Key Vault + UAMI on storage/ACR/PG
  (`encryption` blocks are the marked extension points in the modules) —
  adopt org-wide or not at all, partial CMK gives audit pain for no threat
  reduction.

## Supply chain (spec §14)

- Pinned lock (`requirements/lock.txt` + torch index), pip-audit/bandit in
  CI, SBOM + trivy in Phase 8.
- Images: multi-stage, non-root uid 10001, no privileged containers;
  **digest-pinned in prod parameters**; ACR Premium with export policy off,
  quarantine noted for Phase 8, retention 30 days on untagged.
- Pretrained weights (DINOv2, optional TabPFN/SLM) are SHA-256-pinned and
  fetched at image build only — hence the AML managed network can stay
  approved-outbound-only with **zero** FQDN allowances at run time.
- Model artifacts: joblib only registry-internal and checksum-verified
  (ADR-0012); `torch.load` restricted to `weights_only=True`.

## Detection and audit

- Diagnostic settings on every service → Log Analytics; Defender for Cloud
  and Sentinel are org-level onboarding steps (documented, not in Bicep).
- Policy assignments (audit in dev, enforce in prod) catch portal drift on
  the invariants: storage/KV public access, ACR unrestricted network, KV
  purge protection.
- Application-level: hash-chained audit log with tamper-detecting verify
  endpoint (Phase 5), registry promotion audit (Phase 6), budget alerts at
  80/100% actual and 110% forecast.

## Threat model

The full STRIDE threat model (asset/actor/path/likelihood/impact/controls/
residual/verification per material threat) is a Phase 8 deliverable at
`docs/security/threat-model.md`; the boundaries it will analyze are the ⛨
markers in `data-flow.md`.
