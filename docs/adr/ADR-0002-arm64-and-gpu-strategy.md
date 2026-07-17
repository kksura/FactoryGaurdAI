# ADR-0002: ARM64 container strategy and GPU (GB10/Blackwell) support

Status: Accepted · Date: 2026-07-17

## Context
GB10 is aarch64 with CUDA 13.0 and a Blackwell-class GPU (sm_121). CI runners are x86_64 without GPUs. Some upstream images/wheels lack ARM64 or sm_121 kernels.

## Decision
1. Application images built from `python:3.12-slim` (official multi-arch) — one Dockerfile for arm64+amd64; torch excluded from the serving image.
2. Torch installed in the host venv from the PyTorch cu130 index (fallback cu129, then CPU wheel). GPU capability is *verified* by `make doctor` (real kernel launch), never assumed.
3. If pip CUDA wheels lack sm_121, GPU training runs in the NVIDIA NGC PyTorch container (arm64, CUDA 13) — documented fallback, same training code.
4. Every dependency adoption checks ARM64 wheel/image availability first (recorded in the decision log). Compose services use only multi-arch official images (postgres, minio, prom/prometheus, grafana/grafana) or images we build ourselves (mlflow).
5. All ML code paths run on CPU (smaller batch/profile) so CI and Azure CPU nodes work.

## Alternatives
- NGC container for everything: heavyweight for API/dev loops.
- CPU-only project: wastes the GB10 and fails the performance-engineering requirement.

## Consequences
Uniform dev experience; a documented two-tier GPU story. CI never exercises CUDA kernels — GPU regressions are caught by local/`make doctor` + benchmark runs.

## Security considerations
Official multi-arch base images with digest pinning in production manifests; no third-party "community arm64" images.

## Revisit triggers
`make doctor` shows sm_121 unsupported by the pip wheel; onnxruntime-gpu ARM64 support materializes; Azure ARM64 GPU SKUs become relevant.
