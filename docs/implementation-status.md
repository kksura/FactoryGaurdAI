# Implementation Status

Working-memory file. Update at every phase boundary. Truthful state only — nothing is marked done unless it ran here.

## Current phase
Phase 3 complete. Ready to start Phase 4 (multimodal fusion, calibration,
uncertainty, abstention, root-cause, retrieval).

## Completed
- 2026-07-17: Phase 0 — environment assessment (GB10 ARM64, CUDA 13.0, Docker+GPU verified), planning docs, repo skeleton, git (commit 789ff51).
- 2026-07-17: Phase 1 — pinned venv (unified lock + torch 2.9.1+cu130, GPU verified), layered fail-closed config, JSON logging with redaction, checksum/manifest utils, Makefile + doctor, Dockerfile + compose stack (validated), pre-commit + secrets baseline, PR CI workflow (written, unexecuted), 17 ADRs.
- 2026-07-17: Phase 2 — full synthetic data system: world model with latent truth separation, 10 causal mechanisms with entity-attributed ground truth, production simulation, sensor waveforms, procedural images, graph edges, 4 profiles, validation+quarantine+report, dataset cards, deterministic manifests.
- 2026-07-17: Architecture review v2 approved (DINOv2 vision, serving modes, assistant layer, TabPFN challenger, scope simplifications) — ADR-0018..0021, spec v2 doc + Word export.
- 2026-07-17: Phase 3 — full baseline suite (rule/prior/logistic/HGB+TabPFN/stat-TS/isolation-forest/DINOv2/forecast), leakage-safe temporal+group splits, evaluation report generator, lightweight checksummed artifact persistence. Two real bugs found and fixed during this phase (see decision log D-024/D-025): a generator design flaw that collapsed temporal-split generalization to chance, and an uncalibrated image-quality threshold that detected 0% of degraded images. Both have regression tests now.

## Verified test state
- 62 unit+ml tests green; ruff + mypy clean; tiny/small/medium datasets generate, validate, and train end-to-end (small: 5.3s full pipeline incl. vision). See docs/test-evidence.md.

## Known failures / open issues
- See `docs/open-issues.md`.

## Environment constraints (do not forget)
- ARM64 only. No Azure CLI, no cloud credentials → Azure work is unexecuted-by-design.
- CI will run on x86_64 GitHub runners; keep CPU/tiny paths arch-neutral.
