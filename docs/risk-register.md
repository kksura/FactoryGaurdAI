# Risk Register

Scoring: Likelihood (L) and Impact (I) 1–5. Exposure = L×I. Owner is a role, not a person.

| ID | Risk | L | I | Exp | Mitigation | Owner | Status |
|----|------|---|---|-----|-----------|-------|--------|
| R-01 | ARM64-incompatible dependency discovered mid-build (e.g. onnxruntime-gpu, a security scanner) | 4 | 3 | 12 | Compatibility check before adoption (ADR process); CPU/pure-Python fallback per component; pinned lock tested on this machine | Platform eng | Open |
| R-02 | PyTorch wheel lacks sm_121 (GB10 Blackwell) kernels → GPU unusable from pip wheel | 3 | 4 | 12 | Test `torch.cuda.is_available()` + a real matmul at setup (`make doctor`); fallback to NVIDIA NGC PyTorch container; CPU path always works | ML eng | Open |
| R-03 | Synthetic data too easy → models look unrealistically good, demo overclaims | 4 | 3 | 12 | Causal mechanisms with noise/confounding, label noise option, drift scenarios; report honest metrics; limitations doc | Data science | Open |
| R-04 | Leakage through grouped entities (unit/lot/machine across splits) | 3 | 5 | 15 | Temporal + group-aware splitters with automated leakage tests (tests/ml) | Data science | Open |
| R-05 | Scope: prompt describes months of work; partial delivery misrepresented as complete | 5 | 4 | 20 | `PLAN.md` + `docs/implementation-status.md` track truthfully; acceptance criteria checked per phase; FINAL-REPORT lists gaps explicitly | Lead | Open |
| R-06 | Secrets accidentally committed | 2 | 5 | 10 | .gitignore, detect-secrets pre-commit + CI, `.env.example` only, review before each commit | Security | Open |
| R-07 | Unsafe model deserialization (pickle) from untrusted path | 2 | 5 | 10 | Only load artifacts produced by this project from controlled storage; SHA-256 checksum verification before load; prefer safetensors/ONNX where possible | Security | Open |
| R-08 | Azure design drifts from what Azure actually requires (cannot validate without subscription) | 3 | 3 | 9 | Use current documented AML/Container Apps patterns; lint Bicep; mark everything unexecuted; smoke-test scripts written to be runnable later | Platform eng | Open |
| R-09 | Docker images for observability stack (Grafana/Prometheus/MinIO/Postgres/MLflow) missing ARM64 tags | 2 | 3 | 6 | All chosen images publish linux/arm64 manifests (verified at adoption time in decision log); pin digests | Platform eng | Open |
| R-10 | GPU OOM / unified-memory pressure during medium-profile training alongside desktop use | 3 | 2 | 6 | Batch-size config, gradient accumulation, BF16, memory benchmarks in perf phase | ML eng | Open |
| R-11 | Prompt injection via optional LLM summarizer | 2 | 4 | 8 | LLM disabled by default; input is structured evidence only; output validated against action allow-list; never executes actions | Security | Open |
| R-12 | Data poisoning via feedback endpoint corrupts retraining | 3 | 4 | 12 | Feedback validation, provenance, outlier screening, human approval gate before any retrain promotion | ML eng | Open |
| R-13 | CI (GitHub-hosted, x86_64) diverges from local ARM64 behavior | 3 | 2 | 6 | Arch-neutral code paths, tiny CPU profiles in CI, document ARM-only steps; optional self-hosted runner later | Platform eng | Open |
| R-14 | Long-horizon context loss between work sessions | 4 | 3 | 12 | Persistent working-memory files (`PLAN.md`, `docs/implementation-status.md`, `docs/handoff.md`) updated every phase | Lead | Open |
| R-15 | Cost surprise if Azure IaC is later applied blindly | 2 | 4 | 8 | Budgets + cost alerts in IaC, plan-only CI, explicit cost note per resource in deployment guide, teardown scripts for non-prod | Platform eng | Open |
