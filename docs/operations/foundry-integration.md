# Microsoft Foundry integration (design — unexecuted from the GB10)

FactoryGuard uses Microsoft Foundry for two things (spec §13, ADR-0015):

1. **AI governance surface** — a Foundry project gives the organization one
   place to govern hosted-model access (model catalog allow-listing, quota,
   content-filter policy, audit of model usage) alongside the AML workspace.
2. **Optional Claude Fable 5 summarizer** — the cloud counterpart of the local
   SLM assistant (`FoundrySummarizer` in
   `src/factoryguard/assistants/summarizer.py`), producing the advisory
   summary attached to prediction responses.

Nothing in the platform depends on Foundry: the deterministic
`TemplateSummarizer` is the default and the permanent fallback, and the
assistant output is contractually advisory (`advisory: Literal[True]`,
D-033). If Foundry is never provisioned, everything works.

## Hard constraints (carried over from ADR-0020, enforced in code)

- **Structured evidence only.** The model receives a JSON object assembled
  server-side from enumerated response fields (`FoundrySummarizer._evidence`).
  There is no caller-supplied text path — the prompt-injection surface is
  removed by construction, not by filtering.
- **Validated output with deterministic fallback.** Every generation passes
  `validate_assistant_output` (entity allow-list from the response evidence,
  action taxonomy, probability-language rule). Any violation, SDK absence,
  missing credential, network failure, refusal, or truncation serves the
  template instead — never silence, never unvalidated text.
- **Advisory only.** Nothing parses assistant text back into decisions.

## Wiring (when a subscription exists)

1. Provision a Foundry resource/project in the spoke region; enable the
   Anthropic model family in the model catalog; keep content filtering at the
   org default. Public network access disabled where the org's Foundry SKU
   supports it; otherwise document the exception per ADR-0011.
2. Add the pinned `anthropic` SDK to `requirements/lock.txt` via the normal
   pip-compile flow (it is intentionally absent today — the summarizer
   lazy-imports and falls back).
3. Put the Foundry API key in Key Vault (`foundry-api-key`); expose it to the
   api container as `FG_FOUNDRY_API_KEY` via a Key Vault reference, plus
   `FG_FOUNDRY_RESOURCE=<resource-name>`.
4. Set `assistant.provider: foundry` in the environment config.

```python
# The call the summarizer makes (already implemented):
from anthropic import AnthropicFoundry

client = AnthropicFoundry(api_key=..., resource=...)
message = client.messages.create(
    model="claude-fable-5",   # thinking is always on for Fable 5 — no thinking param
    max_tokens=1024,
    system=FoundrySummarizer._SYSTEM,
    messages=[{"role": "user", "content": evidence_json}],
)
```

## Model-behavior notes (Fable 5)

- `stop_reason == "refusal"` is a normal, handled outcome (HTTP 200): the
  summarizer treats any non-`end_turn` stop as unavailability and serves the
  template. We deliberately do **not** chain a fallback *model* — the
  deterministic template is a better fallback than a second generator, and
  Foundry does not support the server-side `fallbacks` parameter anyway.
- Fable 5 requires 30-day data retention on the provider side; on Foundry the
  retention terms are Microsoft's. Review both against the org's data policy
  before enabling (the evidence payload contains entity ids and scores, no
  personal data — operators are pseudonymous by construction, spec §15).
- Cost control: the summarizer sends ≤1 KB of evidence and caps output at
  1024 tokens per prediction; enable it per-environment, and only for
  responses a human will read (the dashboard), not for batch scoring.

## Rejected alternatives

- **VLM as primary image scorer** — rejected in ADR-0018 (calibration,
  latency, auditability); vision stays DINOv2 + trained heads.
- **LLM output parsed into actions** — forbidden; the recommendation engine
  is deterministic policy code (POL-001..008) and the only action authority.
