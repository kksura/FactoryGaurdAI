# Handoff Note

Updated 2026-07-19 at the end of the Phase 5 session.
Read this first in a new session, then `PLAN.md` and `docs/implementation-status.md`.

## Current phase

**Phases 0–5 complete and committed. Phase 6 (MLOps + observability) not yet started.**

## What exists and works right now

- `make setup && make doctor` → healthy venv, torch 2.9.1+cu130, GPU verified on GB10.
- Data: `python -m pipelines.data.generate|validate --profile <p>`.
- Training: `train_baselines` (Phase 3) and `train_multimodal` (Phase 4+5 serving
  artifacts) — the multimodal run persists everything the API needs
  (`serving_meta`, vision head, cold-start scorers, graph snapshot).
- **API**: `make serve` (needs `FG_AUTH__LOCAL_JWT_SECRET` in `.env`, artifacts for
  `FG_SERVE_PROFILE`, default small). Dev tokens: `python scripts/issue_dev_token.py
  --roles quality-engineer`. Full surface: predictions (+batch, +idempotency),
  feedback, models/card, monitoring, data-quality, approvals, audit verify.
- **Dashboard**: `make dashboard` (Streamlit; reads reports + in-process demo predict).
- `.venv/bin/pytest tests/unit tests/ml tests/contract tests/security tests/end_to_end`
  → 155 tests green; ruff + mypy clean (70 files).

## Next task: Phase 6 — MLOps + observability

Per `PLAN.md`:
- MLflow tracking integration (commit, seeds, checksums, signatures, cards)
- Registry abstraction: Candidate/Validated/Staging/Champion/Archived + promotion gates
- OTel instrumentation; Prometheus metrics; Grafana dashboards (compose stack exists,
  never booted end-to-end — `make up` still unexercised)
- Drift suite (PSI/JS/KS/Wasserstein, embedding drift, calibration drift) — note
  OI-7: drift-aware down-weighting is the planned fix for the weak anomaly-only rule
- Retraining workflow (breach → candidate → compare → approval → shadow/canary)
- GB10 benchmark → `docs/performance/gb10-benchmark.md` (also settles OI-1/OI-2)
- Consider wiring PostgreSQL persistence for serving state (OI-8)

## Things NOT to re-litigate

- Everything in the Phase 4 list (fusion default, conformal+Mahalanobis, Platt slope
  constraint D-028, retrieval embedding D-030) still stands.
- Contract v1 is additive-only: golden schemas in `tests/contract/golden/` are the
  baseline; breaking changes require a `v2` module, never an edit to the goldens.
- Serve-time graph features use the persisted pre-test entity-rate snapshot (D-032);
  don't recompute decayed sums online.
- Assistant constraints are structural (D-033): generators see only the response
  object; validator + template fallback; `advisory` is a Literal[True].
- Local-JWT is dev-only; hardened envs fail-closed to entra-id (already tested).

## Gotchas that still matter

1. `.gitignore` anchoring for new top-level generated dirs (`git check-ignore -v`).
2. Bounded time-features only (D-024); anomaly scores ≠ probabilities.
3. Artifact dirs: lineage.json must stay covered by the manifest (D-031) — write
   order in `persist_artifacts` is lineage → manifest.
4. pandas rows: `row["shift"]` never `row.shift` (method collision).
5. In-memory serving state is per-process (OI-8): rate limits, idempotency and the
   prediction index reset on restart; JSONL logs under `artifacts/serving-logs/` survive.
6. TabPFN needs `TABPFN_TOKEN` (OI-5); vision at serve time needs
   `FG_ENABLE_VISION=1` and the DINOv2 checkpoint cache.

## Environment facts (verified, don't re-verify)

- GB10, ARM64, CUDA 13.0, torch 2.9.1+cu130 (OI-1 capability warning benign).
- No Azure CLI/credentials — Phase 7+ is IaC/docs only. EntraIdVerifier is written
  but unexecuted locally. Repo-local git identity configured.

## Working-memory files to update every phase

`PLAN.md`, `docs/implementation-status.md`, `docs/decision-log.md`,
`docs/open-issues.md`, `docs/test-evidence.md`, this file.
