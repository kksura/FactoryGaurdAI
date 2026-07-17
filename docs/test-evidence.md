# Test Evidence

Append-only log of test/verification runs actually executed on this machine. Each entry: date, command, result summary. Claims of success elsewhere in the docs must trace back to an entry here.

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
