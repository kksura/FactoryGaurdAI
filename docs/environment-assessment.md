# Environment Assessment

Date: 2026-07-17
Host: `promaxgb10-43eb` (Dell GB10-class workstation)
All facts below were verified by running commands on this machine; nothing is assumed.

## Hardware

| Item | Value |
|---|---|
| Platform | NVIDIA GB10 (Grace Blackwell superchip) |
| CPU | 20-core ARM (10× Cortex-X925 + 10× Cortex-A725), aarch64 |
| Memory | 121 GiB unified (CPU/GPU coherent), 15 GiB swap |
| GPU | NVIDIA GB10, unified memory (per-process GPU memory reporting "Not Supported" in nvidia-smi — expected on unified-memory platforms) |
| Disk | 1.9 TB NVMe, 1.7 TB available |

## Software

| Item | Value | Notes |
|---|---|---|
| OS | Ubuntu 24.04.4 LTS (noble), kernel 6.17.0-1014-nvidia | NVIDIA-tuned kernel |
| NVIDIA driver | 580.142 | |
| CUDA | 13.0 (nvcc V13.0.88 installed) | GB10 GPU is Blackwell-generation (sm_121) |
| Python | 3.12.3 (`/usr/bin/python3`), `python3.12-venv` installed | Meets the project's Python 3.12 target |
| pip | 24.0 | `uv`, `poetry`, `conda` not installed |
| Docker | 29.2.1, compose v5.0.2 | overlay2, default runtime runc |
| NVIDIA Container Toolkit | Installed (`nvidia-ctk` present) | **Verified**: `docker run --rm --gpus all ubuntu:24.04 nvidia-smi -L` → `GPU 0: NVIDIA GB10` |
| Podman | Not installed | Docker is the container runtime |
| Git | 2.43.0 | Repo initialized; **no global git identity configured** (commits will use a repo-local identity) |
| Azure CLI | **Not installed** | All Azure operations are design/plan/document only in this environment |
| Azure ML CLI extension | Not applicable (no az) | |
| Make | GNU Make 4.3 | |
| Node.js | v18.19.1 | Sufficient if a light frontend is needed; dashboard will be Streamlit (Python) |

## Consequences for this project

1. **ARM64 (aarch64) everywhere.** Every dependency and container image must have Linux ARM64 support. Known-good on ARM64: PyTorch (aarch64 wheels incl. CUDA builds via pypi cu13x index / NGC containers), scikit-learn, numpy, pandas, pyarrow, FastAPI, Pydantic, MLflow, PostgreSQL, MinIO, Prometheus, Grafana, Redis, Streamlit, NetworkX, onnxruntime (CPU aarch64 wheels; GPU EP availability on CUDA 13/ARM must be tested before relying on it).
2. **GPU compute.** CUDA 13.0 with a Blackwell-class GPU means PyTorch must be a recent build with sm_12x support (PyTorch ≥ 2.7 cu128+ aarch64 wheels, or NVIDIA NGC PyTorch container). CPU-only test paths are mandatory anyway (CI has no GPU).
3. **Unified memory.** 121 GiB shared CPU/GPU. `nvidia-smi` cannot report per-process GPU memory; benchmarking must use `torch.cuda` memory stats plus system-level RSS.
4. **No Azure CLI / no credentials.** Phases that touch Azure produce infrastructure-as-code, job/endpoint definitions, and runbooks that are validated locally where possible (linting, `bicep build` via container if available) but are **not deployed**. Every unexecuted cloud operation is explicitly marked.
5. **No git identity.** A repo-local identity is set so phase commits can be made; the user can amend authorship later.

## Verification commands used

```bash
uname -a; lscpu; free -h; df -h
nvidia-smi; nvcc --version
python3 --version; pip3 --version
docker --version; docker compose version; docker info
docker run --rm --gpus all ubuntu:24.04 nvidia-smi -L   # GPU passthrough: PASS
git --version; az version   # az: command not found
```
