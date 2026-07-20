# Data flow (Azure target)

Trust boundaries are marked ⛨; every crossing authenticates with Entra
(managed identity or user OIDC) and is TLS-encrypted. No connection uses a
shared key or password anywhere in the system.

## Training / promotion flow

```mermaid
flowchart LR
    GEN[Synthetic data generator<br/>pipelines/data] -->|Parquet+PNG+manifest| ADLS[(ADLS curated ⛨)]
    ADLS -->|ro_mount, identity datastore| JOB[AML training job<br/>train_multimodal]
    JOB -->|params/metrics/artifacts| MLF[workspace MLflow]
    JOB -->|checksummed bundle| BLOB[(Blob artifacts ⛨)]
    MLF --> EVAL[evaluation report + model card]
    EVAL --> GATE{promotion gates<br/>metric floors + manifest verify<br/>+ human approval ⛨}
    GATE -->|approve| REG[AML registry: champion]
    GATE -->|reject| STOP[decision file, no promotion]
    REG --> OEP[online endpoint deployment]
```

Lineage invariants (enforced in code, spec §22): every run records git
commit, dataset manifest SHA-256, feature version, seed, config; the serving
bundle is manifest-verified (`verify_manifest`) before **every** load — a
tampered artifact fails closed.

## Online inference flow

```mermaid
flowchart LR
    CLIENT[MES / QA client ⛨] -->|JWT Entra OIDC| API[ca-api<br/>authz, limits, schema]
    API -->|PredictionRequest JSON| OEP[AML online endpoint<br/>score.py → PredictionService ⛨]
    OEP -->|PredictionResponse| API
    API --> PSQL[(PostgreSQL<br/>prediction log)]
    API --> AUD[hash-chained audit log]
    API -.->|structured evidence only| FOUNDRY[Fable 5 summarizer<br/>optional, advisory ⛨]
    API --> CLIENT
    DASH[dashboard] --> API
```

- The API treats scorer responses as **untrusted input** (schema-validated,
  ADR-0008) — a compromised scoring container cannot inject actions.
- Assistant calls carry only the enumerated evidence fields (D-033); no
  caller text reaches the generative model, and its output is advisory
  display text only.
- `hold_unit` / `escalate` recommendations are created `PENDING_APPROVAL` and
  require an authorized human role (ADR-0017) — the model never actuates.

## Feedback / retraining loop

```mermaid
flowchart LR
    QE[Quality engineer ⛨] -->|POST /feedback, role-gated| API[ca-api]
    API --> PSQL[(feedback store)]
    WRK[worker: drift suite] -->|windows over predictions+features| DR[drift report]
    DR --> BREACH{sustained-breach rule<br/>N windows + min samples}
    BREACH -->|yes| RETRAIN[candidate training job]
    RETRAIN --> GATE{gates + champion comparison<br/>+ human approval ⛨}
    GATE -->|approve| CANARY[shadow / canary via endpoint traffic split]
    CANARY -->|health gates pass| PROMOTE[traffic 100%, old kept for rollback]
```

No automatic promotion, ever (spec §21): the breach rule only *creates a
candidate*; a human approves before staging, and canary progression is
gate-checked (runbook §7).

## Data classification and retention

| Data | Store | Class | Notes |
|---|---|---|---|
| Synthetic units/sensors/images | ADLS curated | synthetic (no real data) | reproducible from seed + manifest |
| Model bundles + manifests | Blob `models` | internal | SHA-256 manifest, verified on load |
| Prediction logs | Blob `prediction-logs` + PostgreSQL | internal | no images/tokens; configurable retention (spec §15) |
| Feedback | PostgreSQL | internal | validated against prediction ids |
| Audit log (recommendations, promotions) | Blob (append-only) + PostgreSQL | restricted | hash-chained, tamper-evident; retention-protected storage recommended |
| Telemetry | Log Analytics | internal | redacting formatter; no payloads/secrets in logs |
| Secrets | Key Vault only | secret | RBAC, purge protection, no secrets in code/config/CI |

Operators are pseudonymous by construction and the prohibited-use rule
(no scoring individuals for employment decisions) applies across every flow
(spec §15, `docs/responsible-ai/`).
