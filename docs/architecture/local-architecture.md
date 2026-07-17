# Local Architecture (GB10)

Everything runs on the GB10 workstation: Python processes in a venv for development, Docker Compose for the service stack. GPU access via NVIDIA Container Toolkit (verified) or the host venv.

```mermaid
flowchart LR
    subgraph gen[Data plane]
        SDG[Synthetic data generator] --> VAL[Validation and quarantine]
        VAL --> LAKE[(Parquet + images + sensor windows\nlocal object layout / MinIO)]
        LAKE --> FEAT[Feature pipelines\ntabular / TS / vision / graph]
    end

    subgraph train[Training plane]
        FEAT --> TRAIN[Training pipelines]
        TRAIN --> MLF[MLflow tracking server]
        MLF --> REG[Registry abstraction\nstages + checksums]
    end

    subgraph serve[Serving plane]
        REG --> PRED[Predictor service\nfusion + calibration + abstention]
        PRED --> API[FastAPI apps/api]
        API --> DASH[Streamlit dashboard]
        API --> WORKER[Monitoring worker\ndrift + data quality]
    end

    subgraph state[State]
        PG[(PostgreSQL 16\npredictions, feedback, audit)]
        MINIO[(MinIO\nartifacts, images)]
    end

    API --> PG
    PRED --> MINIO
    MLF --> MINIO
    WORKER --> PG

    subgraph obs[Observability]
        PROM[Prometheus] --> GRAF[Grafana]
    end
    API -. /metrics + OTel .-> PROM
    WORKER -. metrics .-> PROM
```

## Components

| Component | Runs as | Port (localhost only) | Notes |
|---|---|---|---|
| API (`apps/api`) | container / venv | 8000 | non-root, read-only fs where feasible |
| Dashboard (`apps/dashboard`) | container / venv | 8501 | Streamlit |
| Worker (`apps/worker`) | container / venv | — | drift + monitoring loops |
| MLflow | container | 5000 | backend: PostgreSQL, artifacts: MinIO |
| PostgreSQL 16 | container | 5432 | app metadata, predictions, audit |
| MinIO | container | 9000/9001 | S3-compatible object store abstraction |
| Prometheus | container | 9090 | scrapes API/worker |
| Grafana | container | 3000 | provisioned dashboards |

Bindings are `127.0.0.1` only — no public exposure by default (working principle 19).

## Trust boundaries (local)

1. Host ↔ containers (Docker, non-privileged, no docker.sock mounts into app containers).
2. API ↔ callers (dev JWT auth still enforced locally; auth cannot be disabled in prod config).
3. Services ↔ object store / DB (dedicated non-root credentials from `.env`, never committed).
4. Model artifacts (untrusted until checksum-verified against registry manifest).

Expanded security detail: `docs/architecture/security-architecture.md`, threat model in `docs/security/threat-model.md`.
