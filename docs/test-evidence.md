# Test Evidence

Append-only log of test/verification runs actually executed on this machine. Each entry: date, command, result summary. Claims of success elsewhere in the docs must trace back to an entry here.

## 2026-07-17 — Phase 3 baselines + evaluation verification
- `.venv/bin/pytest tests/unit tests/ml -q` → **62 passed** (53 from Phase 2 + 9 new: 6 leakage tests, 2 generalization-regression tests, 1 image-quality regression test).
- ruff clean (`ruff check` + `ruff format --check`, 42 files); mypy "no issues found in 47 source files".
- `python -m pipelines.training.train_baselines --profile small` → full run incl. vision, TabPFN gate check, artifact persistence, in 5.3s. HGB test ROC-AUC 0.713, PR-AUC 0.113. TabPFN correctly reports itself unavailable (`TABPFN_TOKEN not set`). DINOv2 checkpoint checksum verified against pinned SHA-256 (`b938bf1b...`). Artifacts persisted to `artifacts/baselines/small/` (5 files) with SHA-256 manifest + lineage.json.
- `python -m pipelines.training.train_baselines --profile medium --no-tabpfn` → 20.7s, HGB test ROC-AUC 0.544 (consistent with random-CV signal ceiling ~0.55-0.57 measured independently).
- `python -m pipelines.training.train_baselines --profile tiny --no-tabpfn` → runs cleanly (small-sample metrics, as expected for a CI-sized profile).
- **Bug found and fixed (generator)**: HGB temporal-split ROC-AUC on `medium` was 0.469-0.504 (chance) despite a genuine ~0.55-0.57 signal ceiling confirmed via 5-fold random CV. Root cause: `active_tool` was never rotated (dead second tool per machine) and `tool.cycles`/`days_since_maintenance` never reset on replacement, making them unbounded monotonic proxies for elapsed calendar time — disjoint train/test feature ranges a tree model cannot extrapolate across. Fixed: per-tool lognormal wear-rate multiplier, round-robin tool rotation, cycle-counter reset on maintenance, retuned `wear_per_cycle` in all 4 profile configs so multiple wear/maintenance cycles occur within the date range (confirmed: medium went from 0 maintenance events to 207). Also retuned `HgbModel` hyperparameters (regularization) since even post-fix the unregularized 31-leaf/300-iter config still overfit high-cardinality identity categoricals. Post-fix: small test ROC-AUC 0.713, medium 0.544 — both track the measured ceiling. Regression test: `tests/ml/test_generalization.py` (asserts temporal test AUC within 0.08 of the random-CV ceiling; asserts no numeric feature has disjoint train/test ranges).
- **Bug found and fixed (image-quality scorer)**: initial blur-variance threshold (12.0) was an uncalibrated guess — detected 0% of camera-degraded images (Scenario C). Recalibrated empirically against `data/small` (651 images, 31 camera-degraded): threshold 225.0 gives 90.3% detection / 15.2% false-flag rate. Regression test: `tests/unit/test_image_quality.py`.
- Review-driven gap closure (ChatGPT feedback, all adopted except graph-prior cold-start signal and full attention-rollout attribution, deferred to Phase 4 per plan): calib-split wiring into calibration diagnostics; anomaly-score/probability conflation fixed (`anomaly_metrics` vs `classification_metrics`, separate Protocol interfaces); DINOv2 weight checksum pinning; image-quality scorer added; TabPFN explicit precondition gates; lightweight model-artifact persistence with SHA-256 lineage; per-severity recall slicing; report sections for latency/artifact-size/known-limitations.

## 2026-07-17 — Phase 2 synthetic data verification
- `python -m pipelines.data.generate --profile tiny` → 240 units, 7.5% defect rate, 30,720 sensor rows, 125 images, 1,668 graph edges, 0.2 s.
- `python -m pipelines.data.generate --profile small` → 2,500 units, 4.2% defect rate, 651 images, 1.76 s; ground-truth mechanisms present: supplier_lot(10), calibration_offset(6), tool_wear(5), revision_shift(3), changeover(1).
- `python -m pipelines.data.validate --profile tiny|small` → PASSED, 0 quarantined.
- `.venv/bin/pytest tests/unit` → **53 passed** (incl. determinism: two generations produce identical data manifests; validator catches injected unknown-FK/time-travel/schema/corrupt-PNG; hypothesis property tests on mechanisms).
- ruff clean; mypy "no issues in 35 source files" (override for 4 simulation modules documented in pyproject).
- Bug found & fixed during this phase: builtin `hash()` used for per-entity determinism is process-randomized → replaced with SHA-256-based `stable_hash` (would have silently broken reproducibility across runs).

## 2026-07-17 — Phase 1 foundation verification
- `bash scripts/setup_env.sh` → venv built; `requirements/lock.txt` co-resolved (pip-compile) and installed. Two earlier resolution failures (cryptography 49 vs mlflow cap; pandas 3 vs mlflow `pandas<3`) fixed by capping in base.in and unifying the lock.
- `pip install -r requirements/torch.txt --index-url .../whl/cu130` → torch 2.9.1+cu130 aarch64 installed on first attempt.
- `make doctor` → all required checks pass; GPU: "NVIDIA GB10; matmul ok; torch cuda 13.0". torch warns GB10 is capability 12.1 vs supported max 12.0 — kernel ran anyway (recorded as OI-1).
- `.venv/bin/pytest tests/unit -q` → **34 passed**.
- `.venv/bin/ruff check …` → clean. `.venv/bin/mypy` → "no issues found in 26 source files".
- `.venv/bin/bandit -c pyproject.toml -r src apps pipelines scripts` → 2 LOW findings (subprocess in scripts/doctor.py, fixed argv) — accepted.
- `docker compose config -q` (with dummy env) → valid. Workflow + pre-commit YAML parse OK.
- NOT executed: GitHub Actions run (no remote), `make up` full stack boot (deferred to Phase 5 when the API app exists).

## 2026-07-17 — Phase 0 environment verification
- `docker run --rm --gpus all ubuntu:24.04 nvidia-smi -L` → `GPU 0: NVIDIA GB10 (UUID: GPU-b120f6e5-...)` — GPU container passthrough PASS.
- `python3 --version` → 3.12.3; `python3 -m venv --help` → venv available.
- `az version` → command not found (Azure CLI absent; cloud ops unexecuted by design).
