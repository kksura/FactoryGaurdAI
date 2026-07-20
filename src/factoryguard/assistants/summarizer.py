"""Assistant layer (spec §11, ADR-0020) — optional, off by default.

Hard constraints implemented here, not merely documented:

- assistants see **structured evidence only** (the fields of the already-
  assembled response), never raw prompts from callers — there is no
  user-controlled text path into a generator (prompt-injection surface
  removed by construction);
- every generated output is validated by :func:`validate_assistant_output`
  against the evidence entities and the action allow-list; on any failure
  the deterministic template output is served instead (template fallback);
- outputs are marked advisory (`AssistantOutput.advisory` is literally
  ``True`` in the contract) and are a display layer only — nothing parses
  assistant text back into decisions;
- the platform is fully functional with no assistant configured: the
  default is the deterministic :class:`TemplateSummarizer`.
"""

from __future__ import annotations

import logging
import re

from factoryguard.contracts.v1 import AssistantOutput, PredictionResponse
from factoryguard.recommendations.engine import ACTION_TAXONOMY

log = logging.getLogger(__name__)


class TemplateSummarizer:
    """Deterministic summary assembled from response fields (default)."""

    name = "template"

    def summarize(self, response: PredictionResponse) -> AssistantOutput:
        parts: list[str] = []
        if response.abstained:
            reasons = "; ".join(response.abstention_reasons) or "unspecified"
            parts.append(f"The model abstained on this unit ({reasons}).")
        elif response.is_probability and response.defect_probability is not None:
            parts.append(
                f"Estimated defect probability {response.defect_probability:.1%} "
                f"(serving mode: {response.serving_mode})."
            )
        else:
            parts.append(
                f"Relative risk score {response.risk_score:.2f} in "
                f"{response.serving_mode} mode — this is a ranking signal, "
                "not a calibrated probability."
            )
        missing = [m.value for m, s in response.modalities.items() if not s.available]
        if missing:
            parts.append(f"Missing modalities: {', '.join(sorted(missing))}.")
        if response.data_quality != "ok":
            parts.append(f"Data quality: {response.data_quality}.")
        if response.root_causes:
            top = response.root_causes[0]
            parts.append(
                f"Top-ranked cause hypothesis: {top.entity_type} {top.entity_id} "
                "(statistical association, not causal proof)."
            )
        if response.recommendations:
            acts = ", ".join(r.action for r in response.recommendations[:3])
            parts.append(f"Recommended next steps: {acts}.")
        if response.similar_incidents:
            parts.append(
                f"{len(response.similar_incidents)} similar historical incident(s) attached."
            )
        return AssistantOutput(text=" ".join(parts), generator=self.name)


def validate_assistant_output(text: str, response: PredictionResponse) -> list[str]:
    """Return violations (empty = valid).

    Rules: any action-like token must be in the allow-listed taxonomy; any
    entity id mentioned (UNIT-/T-/M-/LOT-/WO- style) must appear in the
    response evidence; no probability claim may be invented outside
    supervised mode.
    """
    violations: list[str] = []
    known_entities = {response.prediction_id}
    for rc in response.root_causes:
        known_entities.add(rc.entity_id)
    for si in response.similar_incidents:
        known_entities.add(si.unit_id)
    for token in re.findall(r"\b(?:UNIT|T|M|LOT|WO|PL|HRN)-[A-Za-z0-9:_-]+", text):
        if token not in known_entities:
            violations.append(f"unknown entity mentioned: {token}")
    for action in re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", text):
        if action not in ACTION_TAXONOMY and any(
            action.startswith(v) for v in ("inspect", "hold", "escalate", "verify", "check")
        ):
            violations.append(f"action outside taxonomy: {action}")
    if (
        not response.is_probability
        and re.search(r"\bprobabilit", text, re.IGNORECASE)
        and "not a calibrated probability" not in text
    ):
        violations.append("probability language outside supervised mode")
    return violations


class SlmSummarizer:
    """Optional local SLM summarizer (ADR-0020). Requires a local model
    runtime that is not part of the pinned environment; when unavailable —
    or whenever its output fails validation — it falls back to the
    template (never to silence, never to unvalidated text)."""

    name = "slm"

    def __init__(self, model_path: str) -> None:
        self.model_path = model_path
        self._fallback = TemplateSummarizer()

    def summarize(self, response: PredictionResponse) -> AssistantOutput:
        try:
            text = self._generate(response)
        except Exception as exc:  # runtime absent, model missing, OOM, …
            log.warning("SLM summarizer unavailable (%s); using template", exc)
            return self._fallback.summarize(response)
        violations = validate_assistant_output(text, response)
        if violations:
            log.warning("SLM output failed validation (%s); using template", violations)
            return self._fallback.summarize(response)
        return AssistantOutput(text=text, generator=self.name)

    def _generate(self, response: PredictionResponse) -> str:
        # Structured evidence only — the model never sees caller-supplied text.
        raise NotImplementedError(
            "local SLM runtime is not installed in this environment (ADR-0020: "
            "optional); the template fallback serves instead"
        )


class FoundrySummarizer:
    """Optional Claude Fable 5 summarizer via Microsoft Foundry (ADR-0015,
    spec §13) — the cloud counterpart of :class:`SlmSummarizer`, with the same
    hard constraints: structured evidence only, validated output, deterministic
    template fallback, contractually advisory.

    Unexecuted in the GB10 environment: the ``anthropic`` SDK is not in the
    pinned lock and no Foundry resource exists here, so every call falls back
    to the template. Wiring is design+code for Phase 7; see
    docs/operations/foundry-integration.md for enabling it in Azure.
    """

    name = "foundry"

    _SYSTEM = (
        "You summarize quality-inspection prediction evidence for factory "
        "operators. You receive a JSON object of structured evidence and "
        "nothing else. Rules: mention only entity ids present in the "
        "evidence; recommend only actions listed in the evidence; if "
        "is_probability is false, never use probability language except the "
        "exact phrase 'not a calibrated probability'; state that root-cause "
        "hypotheses are statistical associations, not causal proof. Your "
        "output is advisory display text — it is never parsed into decisions. "
        "Reply with the summary text only, 2-5 sentences."
    )

    def __init__(self, model: str = "claude-fable-5", resource: str = "") -> None:
        self.model = model
        self.resource = resource
        self._fallback = TemplateSummarizer()

    def summarize(self, response: PredictionResponse) -> AssistantOutput:
        try:
            text = self._generate(response)
        except Exception as exc:  # SDK absent, no credentials, refusal, network …
            log.warning("Foundry summarizer unavailable (%s); using template", exc)
            return self._fallback.summarize(response)
        violations = validate_assistant_output(text, response)
        if violations:
            log.warning("Foundry output failed validation (%s); using template", violations)
            return self._fallback.summarize(response)
        return AssistantOutput(text=text, generator=self.name)

    def _evidence(self, response: PredictionResponse) -> str:
        """Structured evidence only — the same fields the template consumes,
        assembled server-side; no caller-supplied free text reaches the model."""
        import json

        return json.dumps(
            {
                "serving_mode": str(response.serving_mode),
                "is_probability": response.is_probability,
                "defect_probability": response.defect_probability,
                "risk_score": response.risk_score,
                "abstained": response.abstained,
                "abstention_reasons": list(response.abstention_reasons),
                "data_quality": response.data_quality,
                "missing_modalities": sorted(
                    m.value for m, s in response.modalities.items() if not s.available
                ),
                "root_causes": [
                    {"entity_type": rc.entity_type, "entity_id": rc.entity_id, "rank": rc.rank}
                    for rc in response.root_causes
                ],
                "recommended_actions": [r.action for r in response.recommendations],
                "similar_incident_count": len(response.similar_incidents),
            },
            sort_keys=True,
        )

    def _generate(self, response: PredictionResponse) -> str:
        import os

        from anthropic import AnthropicFoundry  # not in the pinned lock → ImportError → template

        client = AnthropicFoundry(
            api_key=os.environ["FG_FOUNDRY_API_KEY"],  # Key Vault-sourced in Azure
            resource=self.resource or os.environ["FG_FOUNDRY_RESOURCE"],
        )
        message = client.messages.create(
            model=self.model,  # Fable 5: thinking always on — no thinking param
            max_tokens=1024,
            system=self._SYSTEM,
            messages=[{"role": "user", "content": self._evidence(response)}],
        )
        if message.stop_reason != "end_turn":  # refusal / max_tokens → deterministic fallback
            raise RuntimeError(f"non-terminal stop_reason {message.stop_reason!r}")
        return "".join(block.text for block in message.content if block.type == "text").strip()


def build_summarizer(
    provider: str, model_path: str = ""
) -> TemplateSummarizer | SlmSummarizer | FoundrySummarizer:
    """Config → summarizer. Unknown providers fall back to the template
    (fail-open to the *deterministic* option, never to a generator)."""
    if provider == "slm" and model_path:
        return SlmSummarizer(model_path)
    if provider == "foundry":
        return FoundrySummarizer()
    if provider not in ("template", ""):
        log.warning("unknown assistant provider %r; using template", provider)
    return TemplateSummarizer()
