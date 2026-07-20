"""Assistant layer: template output, validation, fallback (ADR-0020)."""

from datetime import UTC, datetime

from factoryguard.assistants import (
    FoundrySummarizer,
    SlmSummarizer,
    TemplateSummarizer,
    build_summarizer,
    validate_assistant_output,
)
from factoryguard.contracts.v1 import (
    Modality,
    ModalityStatus,
    PredictionResponse,
    RootCauseCandidate,
    UncertaintyInfo,
)


def _response(**overrides: object) -> PredictionResponse:
    base: dict = {
        "prediction_id": "PRED-abc",
        "correlation_id": "cid",
        "model_version": "m1",
        "feature_version": "tab-v1",
        "serving_mode": "supervised",
        "risk_score": 0.72,
        "is_probability": True,
        "defect_probability": 0.72,
        "confidence": 0.72,
        "uncertainty": UncertaintyInfo(
            conformal_set=["defect"], conformal_alpha=0.1, ambiguous=False, ood=False
        ),
        "abstained": False,
        "abstention_reasons": [],
        "data_quality": "ok",
        "modalities": {
            Modality.TABULAR: ModalityStatus(available=True),
            Modality.VISION: ModalityStatus(available=False, reason="no image"),
        },
        "top_evidence": [],
        "root_causes": [
            RootCauseCandidate(
                rank=1,
                entity_type="tool",
                entity_id="T-PL01-L01-01-1",
                score=0.8,
                history=0.7,
                evidence=0.9,
            )
        ],
        "recommendations": [],
        "similar_incidents": [],
        "assistant": None,
        "processing_ms": 1.0,
        "timestamp": datetime.now(UTC),
    }
    base.update(overrides)
    return PredictionResponse(**base)


def test_template_supervised_mentions_probability_and_caveats() -> None:
    out = TemplateSummarizer().summarize(_response())
    assert out.advisory is True
    assert "72.0%" in out.text
    assert "not causal proof" in out.text
    assert "vision" in out.text  # missing modality surfaced
    assert validate_assistant_output(out.text, _response()) == []


def test_template_anomaly_mode_disclaims_probability() -> None:
    resp = _response(
        serving_mode="anomaly-only",
        is_probability=False,
        defect_probability=None,
        risk_score=0.9,
    )
    out = TemplateSummarizer().summarize(resp)
    assert "not a calibrated probability" in out.text
    assert validate_assistant_output(out.text, resp) == []


def test_validator_flags_unknown_entity_and_foreign_action() -> None:
    resp = _response()
    bad = "Please restart_machine and inspect UNIT-9999999 immediately."
    violations = validate_assistant_output(bad, resp)
    assert any("UNIT-9999999" in v for v in violations)
    # invented probability claims outside supervised mode are flagged too
    resp2 = _response(is_probability=False, serving_mode="blended")
    v2 = validate_assistant_output("The defect probability is high.", resp2)
    assert any("probability" in v for v in v2)


def test_slm_falls_back_to_template_when_unavailable() -> None:
    out = SlmSummarizer("/nonexistent/model.gguf").summarize(_response())
    assert out.generator == "template"  # runtime absent → deterministic fallback
    assert out.text


def test_build_summarizer_defaults_to_template() -> None:
    assert isinstance(build_summarizer(""), TemplateSummarizer)
    assert isinstance(build_summarizer("template"), TemplateSummarizer)
    assert isinstance(build_summarizer("does-not-exist"), TemplateSummarizer)
    assert isinstance(build_summarizer("slm", "/m.gguf"), SlmSummarizer)


def test_foundry_falls_back_to_template_when_sdk_absent() -> None:
    # The anthropic SDK is not in the pinned lock (ADR-0015: optional) —
    # the import inside _generate fails and the template serves instead.
    out = FoundrySummarizer().summarize(_response())
    assert out.generator == "template"
    assert out.text


def test_foundry_invalid_output_falls_back(monkeypatch) -> None:
    fs = FoundrySummarizer()
    monkeypatch.setattr(fs, "_generate", lambda r: "Please restart_machine on UNIT-9999999.")
    out = fs.summarize(_response())
    assert out.generator == "template"


def test_foundry_valid_output_served(monkeypatch) -> None:
    fs = FoundrySummarizer()
    good = (
        "Estimated defect probability 72.0%. Top-ranked cause hypothesis: tool "
        "T-PL01-L01-01-1 (statistical association, not causal proof)."
    )
    monkeypatch.setattr(fs, "_generate", lambda r: good)
    out = fs.summarize(_response())
    assert out.generator == "foundry"
    assert out.text == good


def test_foundry_evidence_contains_no_free_text_fields() -> None:
    # Structured-evidence-only guarantee (D-033): the payload is assembled from
    # enumerated response fields; entity ids and actions, never caller text.
    import json

    payload = json.loads(FoundrySummarizer()._evidence(_response()))
    assert set(payload) == {
        "serving_mode",
        "is_probability",
        "defect_probability",
        "risk_score",
        "abstained",
        "abstention_reasons",
        "data_quality",
        "missing_modalities",
        "root_causes",
        "recommended_actions",
        "similar_incident_count",
    }
    assert payload["root_causes"][0]["entity_id"] == "T-PL01-L01-01-1"


def test_build_summarizer_foundry() -> None:
    assert isinstance(build_summarizer("foundry"), FoundrySummarizer)
