# ADR-0018: Vision architecture — DINOv2 foundation encoder + trained head

Status: Accepted (supersedes the vision portion of the Phase 3/4 plan; user-approved 2026-07-17) · Date: 2026-07-17

## Context
The vision model must serve four consumers: calibrated defect probability (fusion), embeddings (similarity retrieval + embedding fusion), attribution heatmaps, and millisecond batch inference. Plain CNN transfer learning satisfies these but produces mediocre retrieval embeddings and weak few-shot behavior — a real limitation in plants where defect images are scarce. A small VLM was evaluated and rejected as the primary scorer (no native calibrated probabilities, weak/unfaithful attribution, 100–1000× latency, generation nondeterminism, and poor zero-shot transfer to our procedural synthetic images); see the discussion log and ADR-0020 for where a VLM *is* used.

## Decision
Primary vision path: **frozen DINOv2-small (ViT-S/14) encoder + a small trained classification head** (linear or 2-layer MLP), with a k-NN-probe evaluation mode. The encoder's penultimate embeddings feed similarity retrieval and embedding fusion directly. Attribution via Grad-CAM on the final transformer blocks / attention-rollout, validated against known defect geometry in synthetic images. Class imbalance handled at the head (class weights/focal loss). ONNX export of encoder+head where clean.

## Alternatives
- MobileNetV3/ResNet18 transfer (previous plan): lighter, but inferior embeddings and few-shot; no longer justified given DINOv2-small is only ~90 MB and fast on GB10.
- Small VLM as primary: rejected (above).
- Train ViT from scratch: pointless at our data scale.

## Consequences
One backbone serves classification, retrieval, and fusion. Pretrained weights enter the supply chain: pinned revision + SHA-256 checksum recorded in the registry; downloaded once, cached, never fetched at serving time. CPU fallback verified for CI (tiny image counts).

## Security considerations
Weights fetched from the official source at build time only, checksum-verified before use (ADR-0012 loader rules apply).

## Revisit triggers
Real camera data arrives (revisit augmentation/fine-tuning depth); encoder latency budget violated on target hardware.
