# ADR-0021: Scope simplifications and model challengers

Status: Accepted (user-approved 2026-07-17) · Date: 2026-07-17

## Context
Full-architecture review (2026-07-17) identified components whose removal is an improvement, and modeling additions with high value at our data scales.

## Decision
**Removals (improvement by subtraction):**
1. **No local event-stream emulator.** Batch + REST covers every demonstration scenario; Azure Event Hubs remains a documented cloud-phase option behind the ingestion interface. (Deletes a service, its tests, and failure modes.)
2. **No vector database.** Similarity retrieval uses exact in-process search (numpy/FAISS-flat) over ≤10⁵ embeddings; a service-based vector store is unjustified. Revisit only at real production scale.
3. **No feature store.** Feature versioning remains code + config-hash based (recorded in MLflow lineage). Deliberate non-adoption to prevent accidental Feast/feature-platform sprawl.

**Additions (model challengers and robustness):**
4. **TabPFN v2 as tabular challenger** alongside HistGradientBoosting (primary). Config-switched; appears in every model-comparison report; native calibrated probabilities noted in evaluation. HGB remains primary for dependency-weight and SHAP reasons.
5. **Modality-dropout training** for both fusion approaches: random modality masking during training so missing-modality behavior (Scenario E) is trained, not just handled.
6. **Optional self-supervised pretraining** for the 1D-CNN sensor encoder (masked-segment reconstruction on unlabeled waveforms, then supervised fine-tune) behind a config flag; evaluated against the purely supervised encoder.

**Confirmed prior choices:** conformal prediction + Mahalanobis-distance OOD for uncertainty/abstention; 1D-CNN time-series encoder; late fusion default (ADR-0006); time-series foundation models and default-on GNN remain rejected.

## Consequences
Smaller local stack; two additional training paths (TabPFN, SSL) that are strictly optional and config-switched; evaluation reports grow a challenger column and a cold-start section (ADR-0019).

## Security considerations
TabPFN adds pinned pretrained weights to the supply chain — same checksum rules as ADR-0018. Removed services shrink the attack surface.

## Revisit triggers
Dataset scales beyond in-memory retrieval; TabPFN row/feature limits exceeded by the large profile; SSL pretraining shows no measurable lift after Phase 4 evaluation.
