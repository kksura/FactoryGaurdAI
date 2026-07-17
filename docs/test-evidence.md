# Test Evidence

Append-only log of test/verification runs actually executed on this machine. Each entry: date, command, result summary. Claims of success elsewhere in the docs must trace back to an entry here.

## 2026-07-17 — Phase 0 environment verification
- `docker run --rm --gpus all ubuntu:24.04 nvidia-smi -L` → `GPU 0: NVIDIA GB10 (UUID: GPU-b120f6e5-...)` — GPU container passthrough PASS.
- `python3 --version` → 3.12.3; `python3 -m venv --help` → venv available.
- `az version` → command not found (Azure CLI absent; cloud ops unexecuted by design).
