# ADR-0019: Unsupervised-first anomaly mode as a first-class serving mode

Status: Accepted (user-approved 2026-07-17) · Date: 2026-07-17

## Context
Real deployments begin with no quality labels; labels arrive with configurable delay (assumption A14). The original spec treats supervised prediction as the primary path and anomaly detection as a sub-task, leaving the platform notionally useless until labels accumulate.

## Decision
Introduce an explicit **serving mode** dimension with three states, selectable per line/deployment in configuration and reported in every prediction response:
1. `anomaly-only` — no labels yet: TS statistical/reconstruction anomaly + image embedding-distance anomaly (vs a golden-reference set) + tabular isolation forest, combined by a fixed, documented rule into an anomaly-risk score with wide uncertainty and conservative abstention.
2. `blended` — labels accumulating: supervised probabilities blended with anomaly scores via the calibration-period machinery; blend weight is a monitored config value.
3. `supervised` — sufficient labels: supervised fusion primary; anomaly scores remain as OOD/drift evidence and abstention inputs.

Evaluation adds a "cold-start" report: performance of `anomaly-only` mode on the test period as if no labels existed.

## Alternatives
Keep anomaly detection as an internal feature only: simpler, but loses the deploy-from-day-one story and does not reflect operational reality.

## Consequences
Small additional surface (isolation forest + image-distance scorer + mode plumbing); most components already existed in the plan. The demo gains a "works before the first label" scenario.

## Security considerations
None beyond existing model-artifact controls; mode is config, subject to fail-closed validation (a hardened env cannot silently run `anomaly-only` if configured `supervised`).

## Revisit triggers
Blending logic proves confusing in practice; real-world label-latency data suggests different mode thresholds.
