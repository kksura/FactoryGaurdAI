# Changelog

All notable changes to FactoryGuard AI. Format: Keep a Changelog; versioning: SemVer once 0.1.0 ships.

## [Unreleased]

### Added
- Phase 0: environment assessment, implementation plan, assumptions, decision log, risk register, PLAN, repository skeleton, hygiene/tooling configuration.
- Phase 1: pinned dependency locks (unified lock + CUDA torch), layered fail-closed configuration, structured JSON logging with secret redaction, SHA-256 artifact manifest utilities, Makefile + environment doctor, non-root Docker image + local compose stack, pre-commit + detect-secrets baseline, PR CI workflow, 17 architecture decision records, 34 unit tests.
- Phase 2: synthetic data system — linked entity world model, 10 configurable causal defect mechanisms with entity-attributed root-cause ground truth, chronological production simulation, crimp-force/aux sensor waveforms with realistic nuisances, procedural inspection images with camera-drift windows, typed graph edges, tiny/small/medium/large profiles, Pandera validation with quarantine and data-quality reports, dataset cards and checksummed manifests.
- Architecture review v2 (ADR-0018..0021): DINOv2 vision, unsupervised-first serving modes, optional local assistant layer, TabPFN challenger, scope simplifications; published as `docs/specification/factoryguard-spec-v2.md` + Word export.
- Phase 3: baseline models + evaluation framework — temporal/group-aware split framework with leakage tests, rule/prior/logistic/HGB(+TabPFN challenger)/statistical-TS/isolation-forest/DINOv2-vision/frequency-forecast baselines, common model interfaces, checksum-verified pretrained vision weights, image-quality scorer (Scenario C), lightweight checksummed model-artifact persistence, evaluation report generator with challenger/cold-start/severity-slice/calibration sections.

### Fixed
- Data generator: tool wear/maintenance design made time-correlated features unbounded and monotonic, collapsing temporal-split model generalization to chance despite real underlying signal (see decision log D-024).
- Image-quality scorer: blur-detection threshold was an uncalibrated guess that missed 100% of degraded images; recalibrated against real data (D-027).
