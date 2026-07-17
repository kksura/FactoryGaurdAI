# Open Issues

| ID | Opened | Issue | Impact | Next action |
|----|--------|-------|--------|------------|
| OI-1 | 2026-07-17 | **Partially resolved.** torch 2.9.1+cu130 installed; GPU matmul works on GB10, but torch warns "cuda capability 12.1 … supported (8.0)-(12.0)" — kernels run via sm_120/PTX compatibility | Functional; watch for per-op failures or perf loss in Phase 6 benchmarks | Benchmark in Phase 6; if unstable, switch to NGC PyTorch container (ADR-0002 fallback) |
| OI-2 | 2026-07-17 | onnxruntime GPU EP on aarch64/CUDA13 unverified | ONNX export path may be CPU-only locally | Test in Phase 6 benchmark; ONNX export remains optional |
| OI-3 | 2026-07-17 | No git global identity; using repo-local placeholder identity | Commit authorship is placeholder | User may set real identity and amend if desired |
| OI-4 | 2026-07-17 | GitHub Actions CI cannot be executed from this environment (no remote configured) | CI workflows are written and lint-checked but unverified on GitHub | Mark as unexecuted; user pushes to GitHub to activate |
