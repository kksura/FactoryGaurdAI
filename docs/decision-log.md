# Decision Log

Chronological log of significant decisions. Architecture Decision Records with full context/alternatives/consequences live in `docs/adr/`; this file is the running index plus lightweight decisions that don't need a full ADR.

| # | Date | Decision | Rationale | ADR |
|---|------|----------|-----------|-----|
| D-001 | 2026-07-17 | Project folder named `FactoryGuardAI` (correcting the requested "FactoryGaurdAI" typo) to match the product name in the specification | Consistency with all docs and package names | — |
| D-002 | 2026-07-17 | Python 3.12 + `venv` + `pip-tools`-style pinned requirements (compiled lock files), no conda/poetry | 3.12.3 is preinstalled with venv; simplest reproducible path on ARM64; lock files give pinning + hashes | ADR-0001 |
| D-003 | 2026-07-17 | PyTorch from official aarch64 CUDA wheel index; fall back to NGC container if sm_121 unsupported; CPU path mandatory everywhere | GB10 is Blackwell (sm_121), CUDA 13.0 host | ADR-0002 |
| D-004 | 2026-07-17 | Parquet for analytical tables; directory hierarchy + PNG for images; Parquet (long format) for sensor windows; JSON sidecar manifests with SHA-256 checksums | Columnar, portable, ARM64-safe via pyarrow | ADR-0003 |
| D-005 | 2026-07-17 | MLflow for experiment tracking + a thin registry abstraction over it (local file/MinIO backend now, Azure ML registry later) | MLflow is ARM64-fine, AML speaks MLflow natively → local/cloud parity | ADR-0004/0005 |
| D-006 | 2026-07-17 | Graph: NetworkX feature pipeline first; optional PyG GraphSAGE behind a config flag, off by default | Working principle "reliable baseline before GNN"; PyG wheels on aarch64 need verification | ADR-0007 |
| D-007 | 2026-07-17 | Serving: FastAPI in Docker locally; Azure Container Apps for the API + AML Managed Online Endpoint for model scoring in cloud | Least-complex services satisfying requirements; AKS documented as scale-out alternative | ADR-0008/0009 |
| D-008 | 2026-07-17 | AuthN/AuthZ: pluggable provider interface — local signed JWT (dev-only issuer) now, Entra ID OIDC in cloud; role/scope model identical in both | Keeps local and cloud behavior aligned | ADR-0010 |
| D-009 | 2026-07-17 | Model serialization: safetensors/ONNX preferred; torch `state_dict` + SHA-256 manifest where needed; never `torch.load` untrusted files (`weights_only=True` enforced) | Supply-chain and deserialization safety | ADR-0012 |
| D-010 | 2026-07-17 | IaC: Bicep primary (Azure-native, no state file secret risk), Terraform equivalent documented as partial | Azure-only target; AML/Foundry examples are first-class in Bicep | ADR-0013 |
| D-011 | 2026-07-17 | CI: GitHub Actions with OIDC workload-identity federation for any future Azure steps; no stored cloud secrets | Prompt requirement; standard practice | ADR-0014 |
| D-012 | 2026-07-17 | Optional LLM (Fable 5 via Foundry or Anthropic API) only summarizes structured evidence; disabled by default; output validated against action allow-list | Working principle 20 | ADR-0015 |
| D-013 | 2026-07-17 | Dashboard: Streamlit (ARM64 pure-Python) instead of React frontend | Team is Python-first; lowest complexity satisfying §19 | — |
| D-014 | 2026-07-17 | Local stack via Docker Compose: PostgreSQL 16, MinIO, MLflow, Prometheus, Grafana, API, dashboard, worker; Redis omitted until a demonstrated need | Working principle 5; Redis "only when justified" | — |
| D-015 | 2026-07-17 | Repo-local git identity `FactoryGuard AI <factoryguard@localhost>` because no global identity configured; user can amend | Enables per-phase commits | — |
| D-016 | 2026-07-17 | Dataframe validation: Pandera (ARM64 pure-Python) for dataframe schemas + Pydantic v2 for API/event payloads | Both install cleanly on aarch64 | ADR-0006 (data contracts) |
