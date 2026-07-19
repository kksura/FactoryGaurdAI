"""Contract compatibility tests (spec §18).

The golden JSON Schemas under ``golden/`` are the v1 baseline. Within v1,
changes must be additive: a field that ever existed may not disappear or
become newly required. Breaking either rule fails here — the fix is a v2
contract module, not an edit to the golden files.
"""

import json
from pathlib import Path

import pytest

from factoryguard.contracts.v1 import (
    SCHEMA_VERSION,
    ApprovalRequest,
    FeedbackRequest,
    FeedbackResponse,
    PredictionRequest,
    PredictionResponse,
)

GOLDEN = Path(__file__).parent / "golden"
MODELS = [PredictionRequest, PredictionResponse, FeedbackRequest, FeedbackResponse, ApprovalRequest]


def _walk_defs(schema: dict) -> dict[str, dict]:
    """name → object schema for the root and every $defs entry."""
    out = {"__root__": schema}
    out.update(schema.get("$defs", {}))
    return out


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_backward_compatible_with_golden(model: type) -> None:
    golden = json.loads((GOLDEN / f"{model.__name__}.json").read_text())
    current = model.model_json_schema()
    g_defs, c_defs = _walk_defs(golden), _walk_defs(current)
    for name, g in g_defs.items():
        assert name in c_defs, f"schema object {name} was removed (breaking)"
        c = c_defs[name]
        g_props = set(g.get("properties", {}))
        c_props = set(c.get("properties", {}))
        missing = g_props - c_props
        assert not missing, f"{name}: fields removed (breaking): {missing}"
        newly_required = (
            set(c.get("required", []))
            - set(g.get("required", []))
            - (
                c_props - g_props  # brand-new fields may be required only if additive-safe
            )
        )
        assert not newly_required, (
            f"{name}: previously-optional fields became required (breaking): {newly_required}"
        )


def test_schema_version_constant() -> None:
    assert SCHEMA_VERSION == "1.0"
    assert PredictionResponse.model_fields["schema_version"].default == SCHEMA_VERSION


def test_request_rejects_unknown_fields() -> None:
    with pytest.raises(Exception, match="unit"):
        PredictionRequest.model_validate({"unexpected": 1})


def test_assistant_output_is_always_advisory() -> None:
    from factoryguard.contracts.v1 import AssistantOutput

    out = AssistantOutput(text="hello", generator="template")
    assert out.advisory is True
    with pytest.raises(Exception, match="advisory"):
        AssistantOutput.model_validate({"text": "x", "generator": "template", "advisory": False})
