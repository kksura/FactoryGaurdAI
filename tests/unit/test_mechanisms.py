"""Property-based tests for the causal mechanism engine."""

from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from factoryguard.data import mechanisms as mech
from factoryguard.data.profiles import load_profile

CONFIGS = Path(__file__).resolve().parents[2] / "configs" / "data"
PROFILE = load_profile("tiny", CONFIGS)


def _ctx(**overrides: object) -> mech.UnitContext:
    base: dict[str, object] = {
        "tool_wear": 0.2,
        "tool_id": "T-1",
        "machine_id": "M-1",
        "line_id": "L-1",
        "plant_id": "PL01",
        "shift": "day",
        "terminal_lot_id": "LOT-1",
        "terminal_lot_is_bad": False,
        "humidity_pct": 50.0,
        "product_has_seal": True,
        "calibration_offset_mm": 0.0,
        "is_first_piece_after_changeover": False,
        "changeover_inadequate": False,
        "work_order_id": "WO-1",
        "days_since_maintenance": 30.0,
        "production_rate_uph": 45.0,
        "revision_shifted": False,
        "product_id": "HRN-1001",
        "revision": "A",
    }
    base.update(overrides)
    return mech.UnitContext(**base)  # type: ignore[arg-type]


@given(
    wear=st.floats(0.0, 1.3),
    humidity=st.floats(0.0, 100.0),
    bad=st.booleans(),
    offset=st.sampled_from([0.0, 0.07, -0.07]),
    shift=st.sampled_from(["day", "evening", "night"]),
    dsm=st.floats(0.0, 60.0),
)
@settings(max_examples=200, deadline=None)
def test_probabilities_always_valid(
    wear: float, humidity: float, bad: bool, offset: float, shift: str, dsm: float
) -> None:
    ctx = _ctx(
        tool_wear=wear,
        humidity_pct=humidity,
        terminal_lot_is_bad=bad,
        calibration_offset_mm=offset,
        shift=shift,
        days_since_maintenance=dsm,
    )
    logits, contribs = mech.category_logits(ctx, PROFILE)
    assert set(logits) == set(mech.CATEGORIES)
    for lg in logits.values():
        assert 0.0 <= mech.probability(lg) <= 1.0
    for c in contribs:
        assert c.category in mech.CATEGORIES
        assert c.entity_id


@given(wear_lo=st.floats(0.0, 0.5), wear_hi=st.floats(0.55, 1.3))
@settings(max_examples=100, deadline=None)
def test_tool_wear_is_monotone_risk(wear_lo: float, wear_hi: float) -> None:
    lo, _ = mech.category_logits(_ctx(tool_wear=wear_lo), PROFILE)
    hi, _ = mech.category_logits(_ctx(tool_wear=wear_hi), PROFILE)
    assert hi["crimp_height_oot"] >= lo["crimp_height_oot"]
    assert hi["crimp_force_anomaly"] >= lo["crimp_force_anomaly"]


def test_bad_lot_raises_only_deformation() -> None:
    clean, _ = mech.category_logits(_ctx(terminal_lot_is_bad=False), PROFILE)
    bad, contribs = mech.category_logits(_ctx(terminal_lot_is_bad=True), PROFILE)
    assert bad["terminal_deformation"] > clean["terminal_deformation"]
    assert bad["missing_seal"] == clean["missing_seal"]
    assert any(c.mechanism == "supplier_lot" and c.entity_type == "material_lot" for c in contribs)


def test_recent_maintenance_reduces_crimp_risk() -> None:
    fresh, _ = mech.category_logits(_ctx(days_since_maintenance=0.5), PROFILE)
    stale, _ = mech.category_logits(_ctx(days_since_maintenance=30.0), PROFILE)
    assert fresh["crimp_height_oot"] < stale["crimp_height_oot"]


def test_humidity_needs_seal_product() -> None:
    sealed, contribs = mech.category_logits(_ctx(humidity_pct=90.0, product_has_seal=True), PROFILE)
    unsealed, _ = mech.category_logits(_ctx(humidity_pct=90.0, product_has_seal=False), PROFILE)
    assert sealed["missing_seal"] > unsealed["missing_seal"]
    assert any(c.mechanism == "humidity" for c in contribs)


def test_severity_covers_all_categories() -> None:
    assert set(mech.SEVERITY) == set(mech.CATEGORIES)
    assert set(mech.SEVERITY.values()) <= {"minor", "major", "critical"}
