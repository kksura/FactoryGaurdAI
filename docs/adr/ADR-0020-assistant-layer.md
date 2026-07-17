# ADR-0020: Local assistant layer (SLM summarizer + VLM vision triage)

Status: Accepted (user-approved 2026-07-17; extends ADR-0015) · Date: 2026-07-17

## Context
ADR-0015 defined an optional hosted-LLM summarizer with a deterministic template default. The user wants on-box generative assistance on the GB10 (121 GiB unified memory comfortably runs 2–8B models), and a vision-language second opinion for human reviewers — without violating working principle 20 (no generative model makes operational decisions).

## Decision
One `Assistant` abstraction with two roles and three implementations each where applicable:
- **Explanation summarizer**: `TemplateSummarizer` (default, deterministic) → optional `LocalSlmSummarizer` (small instruct model served on-box, e.g. via an OpenAI-compatible local runtime) → optional hosted Fable 5 (cloud, per ADR-0015).
- **Vision triage assistant** (new): optional `LocalVlmAssistant` (2–3B vision-language model) invoked ONLY for (a) abstained/borderline images queued for human review and (b) generating textual defect descriptions in explanation reports.

Hard constraints enforced in code for every implementation: structured-evidence-only inputs; outputs validated against evidence entities and the allow-listed action taxonomy with template fallback on violation; display/triage layer only — never an input to scores, thresholds, recommendations, or promotion gates; disabled by default; platform fully functional with none configured.

## Alternatives
Hosted-only assistants (data leaves the box — weak story for manufacturing); VLM in the scoring path (rejected, ADR-0018).

## Consequences
New optional runtime dependency (local model server) documented as strictly optional; assistant outputs carry a "generated, advisory" marker in UI and API. Demo gains a fully offline generative-AI capability.

## Security considerations
Prompt-injection surface remains minimal (no free-text user input reaches assistants); local model weights pinned + checksummed; assistant outputs treated as untrusted display data (escaped in UI, never executed or parsed into actions).

## Revisit triggers
Interactive incident Q&A requirement; local runtime maintenance burden; Foundry-hosted small models becoming preferable.
