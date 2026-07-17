# Security Policy

## Reporting a vulnerability

This is a reference implementation developed on a private workstation. If you find a security issue:

1. Do **not** open a public issue with exploit details.
2. Email the maintainer (repository owner) with: affected component, reproduction steps, impact assessment.
3. Expect acknowledgment within 5 business days.

## Scope

In scope: API authentication/authorization, input validation, model artifact integrity, secret handling, container configuration, dependency vulnerabilities, IaC misconfigurations.

Out of scope: attacks requiring physical access to the development workstation; the synthetic data generator producing "realistic" values (it contains no real data by design).

## Design commitments

- Deny-by-default authorization; least privilege identities (local JWT dev issuer, Entra ID in cloud).
- No secrets in source control; `.env` ignored; detect-secrets in pre-commit and CI.
- Model artifacts are loaded only from controlled storage after SHA-256 verification; `torch.load` is always called with `weights_only=True`.
- All untrusted input (API payloads, images, feedback) is schema-validated, size-limited, and content-type-checked before processing.
- Containers run non-root, without privileged mode, with dropped capabilities.
- Dependencies are pinned; pip-audit/bandit/trivy run in CI; SBOMs generated per release.

See `docs/security/` for the threat model and full security architecture.
