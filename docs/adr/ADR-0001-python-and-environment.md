# ADR-0001: Python 3.12 with venv + pip-tools lock files

Status: Accepted · Date: 2026-07-17

## Context
Local target is an ARM64 GB10 workstation with Python 3.12.3 preinstalled. The project needs pinned, reproducible dependencies (spec §2.13) across local ARM64, x86_64 CI, and Azure images, without introducing tool sprawl.

## Decision
Python 3.12, standard `venv`, and pip-tools: human-edited `requirements/*.in` co-resolved into a single `requirements/lock.txt`; torch pinned separately in `requirements/torch.txt` because its CUDA aarch64 build comes from the PyTorch index. `pyproject.toml` carries metadata/tooling config only; installs always use the lock.

## Alternatives
- **uv**: faster, but adds a new binary dependency; pip-tools is sufficient and boring.
- **poetry/conda**: heavier, conda solves nothing here (all wheels available), poetry's resolver fights index-pinned torch.

## Consequences
Reproducible installs; lock recompiled deliberately, drift visible in git. Two-step torch install is a documented quirk. Lock is compiled on ARM64; x86 CI resolves the same pins (universal wheels except torch, which CI installs CPU-only).

## Security considerations
Pinned versions enable pip-audit against the exact lock; hash-checking can be added with `--generate-hashes` once multi-platform hash coverage is verified.

## Revisit triggers
Python 3.13 adoption; uv standardization in the org; lock/hash conflicts across platforms.
