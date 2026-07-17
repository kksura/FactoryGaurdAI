# Open Issues

| ID | Opened | Issue | Impact | Next action |
|----|--------|-------|--------|------------|
| OI-1 | 2026-07-17 | PyTorch aarch64 wheel support for GB10 (sm_121, CUDA 13) unverified | GPU training path uncertain until tested | Phase 1: install torch, run `make doctor` GPU matmul check; fallback NGC container per ADR-0002 |
| OI-2 | 2026-07-17 | onnxruntime GPU EP on aarch64/CUDA13 unverified | ONNX export path may be CPU-only locally | Test in Phase 6 benchmark; ONNX export remains optional |
| OI-3 | 2026-07-17 | No git global identity; using repo-local placeholder identity | Commit authorship is placeholder | User may set real identity and amend if desired |
| OI-4 | 2026-07-17 | GitHub Actions CI cannot be executed from this environment (no remote configured) | CI workflows are written and lint-checked but unverified on GitHub | Mark as unexecuted; user pushes to GitHub to activate |
