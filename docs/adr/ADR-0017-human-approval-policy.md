# ADR-0017: Human approval policy

Status: Accepted · Date: 2026-07-17

## Context
The system is advisory. Model promotion and high-impact recommendations require human approval; the LLM (if any) has no operational authority.

## Decision
Two approval domains, both enforced in code and audited:
1. **Model promotion**: transitions into Staging and Champion require a recorded approval (`approver identity`, `role=ml-engineer|platform-admin`, timestamp, gate report hash) in the registry event log. CI release pipelines mirror this with GitHub `environment` required reviewers. No API exists to skip gates; emergency rollback (Champion → previous version) is the only fast path and is itself audited.
2. **Recommendations**: every policy rule declares `severity` and `required_approver_role`. Actions at severity ≥ high (e.g. hold units, lot quarantine escalation) are emitted in state `PENDING_APPROVAL` and are only marked actionable after an authorized approval via the feedback/approval endpoint. Low-severity advisories (e.g. "verify crimp-height measurement") are informational and need no approval. Expiration timestamps prevent stale approvals.

## Alternatives
Fully manual release management (no codified gates): unauditable. Auto-promotion on metrics: forbidden by spec.

## Consequences
Demo includes a failed-gate scenario (G) and an approval flow; local development simulates approvers with dev tokens carrying the proper roles.

## Security considerations
Approval records are append-only with hash chaining (tamper-evident); approver role verified from the token, not the request body.

## Revisit triggers
Integration with a corporate change-management system (ServiceNow etc.).
