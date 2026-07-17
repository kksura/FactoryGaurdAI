# ADR-0015: Optional LLM use — summarization only, disabled by default

Status: Accepted · Date: 2026-07-17

## Context
Spec permits an LLM to summarize structured evidence but forbids it from inventing measurements/causes/actions or driving operational decisions; the platform must work with no LLM configured.

## Decision
`factoryguard.explainability.summarizer` defines a `Summarizer` interface with a default **TemplateSummarizer** (deterministic, always available). An optional **LlmSummarizer** (Anthropic Fable 5 via Foundry or the Anthropic API) activates only when explicitly configured. Constraints enforced in code, not prompts:
- Input is the structured evidence JSON only (no free user text → no injection channel from API callers).
- Output must validate: referenced entity IDs/values must exist in the input evidence; recommended actions must be IDs from the allow-listed taxonomy; otherwise the template output is used and the event logged.
- The LLM result never feeds the recommendation engine, thresholds, or any decision — display-layer only.

## Alternatives
Local small LLM: extra GPU/ops burden for prose; template output is acceptable.

## Consequences
No availability or safety dependency on an external AI service; the demo runs fully offline.

## Security considerations
Prompt-injection surface minimized by structured-input-only design; API key via Key Vault/env, never logged; responses treated as untrusted and validated.

## Revisit triggers
Interactive Q&A over incidents is requested; Foundry evaluation tooling adoption.
