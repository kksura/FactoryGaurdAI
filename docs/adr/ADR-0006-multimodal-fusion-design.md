# ADR-0006: Multimodal fusion design

Status: Accepted · Date: 2026-07-17

## Context
Four modalities (tabular, time series, images, graph) with realistic missingness. Spec requires two comparable fusion approaches and forbids interpreting a missing modality as a zero-valued normal observation.

## Decision
1. **Late fusion (reference)**: each modality model outputs an independently calibrated probability; a meta-classifier (logistic regression over modality scores + availability mask + per-modality uncertainty) produces the final score. Robust, debuggable, per-modality attribution for free.
2. **Embedding fusion (advanced)**: fixed-size embeddings per modality (tabular projection, TS encoder, vision backbone penultimate layer, graph feature vector) concatenated with a learned gating layer conditioned on the availability mask; missing modalities contribute a learned "absent" embedding, never zeros.
Both trained/evaluated under the same splits; comparison is part of the standard evaluation report. Late fusion is the default serving path until embedding fusion demonstrably wins including calibration and missing-modality robustness.

## Alternatives
Cross-modal attention transformers: overkill at synthetic-data scale, harder to calibrate and explain. Single monolithic model: violates modality-replaceability and abstention design.

## Consequences
Two code paths to maintain, mitigated by a shared `FusionInput` contract (embeddings + masks). Missing-modality behavior becomes a first-class tested property (Scenario E).

## Security considerations
Modality inputs validated independently; a poisoned single modality degrades gracefully and is visible in per-modality attributions.

## Revisit triggers
Embedding fusion consistently better calibrated; real multimodal data volumes.
