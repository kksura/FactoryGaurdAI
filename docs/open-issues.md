# Open Issues

| ID | Opened | Issue | Impact | Next action |
|----|--------|-------|--------|------------|
| OI-1 | 2026-07-17 | **Partially resolved.** torch 2.9.1+cu130 installed; GPU matmul works on GB10, but torch warns "cuda capability 12.1 … supported (8.0)-(12.0)" — kernels run via sm_120/PTX compatibility | Functional; watch for per-op failures or perf loss in Phase 6 benchmarks | Benchmark in Phase 6; if unstable, switch to NGC PyTorch container (ADR-0002 fallback) |
| OI-2 | 2026-07-17 | onnxruntime GPU EP on aarch64/CUDA13 unverified | ONNX export path may be CPU-only locally | Test in Phase 6 benchmark; ONNX export remains optional |
| OI-3 | 2026-07-17 | No git global identity; using repo-local placeholder identity | Commit authorship is placeholder | User may set real identity and amend if desired |
| OI-4 | 2026-07-17 | GitHub Actions CI cannot be executed from this environment (no remote configured) | CI workflows are written and lint-checked but unverified on GitHub | Mark as unexecuted; user pushes to GitHub to activate |
| OI-5 | 2026-07-17 | TabPFN challenger requires a free `TABPFN_TOKEN` license token (interactive browser acceptance) not available in this environment | Challenger reports itself unavailable with a clear reason; HGB primary is unaffected | User can set `TABPFN_TOKEN` in `.env` after accepting the license at https://ux.priorlabs.ai to enable the challenger comparison |
| OI-6 | 2026-07-17 | Unseen-line generalization (HGB) is weak (~chance) on `medium` — a genuinely hard transfer task (new machines/tools never seen in training) | Honestly reported, not hidden; graph-derived features (Phase 4) may help via non-identity risk signals | Re-measure after Phase 4 graph features land |

**Resolved this phase — recorded for the audit trail:**

| ID | Found | Issue | Impact | Resolution |
|----|-------|-------|--------|-----------|
| OI-R1 | 2026-07-17 | `.gitignore`'s unanchored `data/` pattern matched `src/factoryguard/data/`, `configs/data/`, and `pipelines/data/` (any directory named `data` anywhere), silently excluding the entire Phase 2 synthetic-data-system source code from every commit since Phase 2 — the Phase 2 commit message claimed these files were added, but `git show --stat` proved they never were | All Phase 2/3 work on the data generator existed only on disk, never in git history, until caught while staging the Phase 3 commit | Anchored `data/`, `artifacts/`, `secrets/`, `mlruns/`, `mlartifacts/`, `reports/` to the repo root with a leading slash in `.gitignore`; verified via `git check-ignore -v` that no source subdirectory is caught; all previously-untracked files added in the Phase 3 commit |
