"""Causal defect mechanisms.

Labels are never assigned randomly: each unit's per-category defect
probability is composed from a calibrated baseline plus contributions from
configurable latent mechanisms. Every contribution carries the entity it
acts through, giving the known ground truth used to evaluate root-cause
ranking (spec §5.5, §9).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from factoryguard.data.profiles import Profile

CATEGORIES = [
    "crimp_height_oot",
    "crimp_force_anomaly",
    "terminal_deformation",
    "missing_seal",
    "damaged_insulation",
    "partial_insertion",
    "wrong_wire",
    "labeling_error",
]

SEVERITY = {
    "crimp_height_oot": "major",
    "crimp_force_anomaly": "major",
    "terminal_deformation": "critical",
    "missing_seal": "major",
    "damaged_insulation": "minor",
    "partial_insertion": "critical",
    "wrong_wire": "critical",
    "labeling_error": "minor",
}

# Categories a mechanism can plausibly cause. Background-only categories
# (wrong_wire, labeling_error, damaged_insulation) mostly stay at baseline.
_CRIMP_CATS = ("crimp_height_oot", "crimp_force_anomaly")


@dataclass(frozen=True)
class Contribution:
    mechanism: str
    category: str
    delta_logit: float
    entity_type: str
    entity_id: str


@dataclass
class UnitContext:
    """Latent + observable state of one unit at production time."""

    tool_wear: float  # 0..~1.2, latent true wear of the active tool
    tool_id: str
    machine_id: str
    line_id: str
    plant_id: str
    shift: str
    terminal_lot_id: str
    terminal_lot_is_bad: bool
    humidity_pct: float
    product_has_seal: bool
    calibration_offset_mm: float  # 0 when machine/family not affected
    is_first_piece_after_changeover: bool
    changeover_inadequate: bool
    work_order_id: str
    days_since_maintenance: float
    production_rate_uph: float
    revision_shifted: bool
    product_id: str
    revision: str


def base_logit(profile: Profile) -> float:
    """Per-category baseline logit calibrated so that, absent mechanisms,
    P(any defect) ≈ 0.6 × target rate (mechanisms supply the rest)."""
    target_any = 0.6 * profile.production.target_defect_rate
    per_cat = 1.0 - (1.0 - target_any) ** (1.0 / len(CATEGORIES))
    per_cat = min(max(per_cat, 1e-6), 0.5)
    return math.log(per_cat / (1.0 - per_cat))


def contributions(ctx: UnitContext, profile: Profile) -> list[Contribution]:
    mech = profile.mechanisms
    out: list[Contribution] = []

    def cfg(name: str):  # type: ignore[no-untyped-def]
        c = mech.get(name)
        return c if c is not None and c.enabled else None

    if (c := cfg("tool_wear")) is not None and ctx.tool_wear > 0.5:
        excess = (ctx.tool_wear - 0.5) / 0.5
        strength = c.param("strength", 2.2)
        for cat in _CRIMP_CATS:
            out.append(Contribution("tool_wear", cat, strength * excess, "tool", ctx.tool_id))

    if (c := cfg("supplier_lot")) is not None and ctx.terminal_lot_is_bad:
        out.append(
            Contribution(
                "supplier_lot",
                "terminal_deformation",
                c.param("strength", 2.5),
                "material_lot",
                ctx.terminal_lot_id,
            )
        )

    if (c := cfg("humidity")) is not None and ctx.product_has_seal:
        threshold = c.param("threshold_pct", 70.0)
        if ctx.humidity_pct > threshold:
            scale = min(1.5, (ctx.humidity_pct - threshold) / 20.0)
            out.append(
                Contribution(
                    "humidity",
                    "missing_seal",
                    c.param("strength", 1.8) * scale,
                    "plant",
                    ctx.plant_id,
                )
            )

    if (c := cfg("calibration_offset")) is not None and ctx.calibration_offset_mm != 0.0:
        out.append(
            Contribution(
                "calibration_offset",
                "crimp_height_oot",
                c.param("strength", 2.0),
                "machine",
                ctx.machine_id,
            )
        )

    if (
        (c := cfg("changeover")) is not None
        and ctx.is_first_piece_after_changeover
        and ctx.changeover_inadequate
    ):
        out.append(
            Contribution(
                "changeover",
                "partial_insertion",
                c.param("strength", 1.6),
                "work_order",
                ctx.work_order_id,
            )
        )

    # Interaction: only bites when the shift is night AND the tool is already
    # worn AND load is high.
    if (
        (c := cfg("night_shift_load")) is not None
        and ctx.shift == "night"
        and ctx.tool_wear > 0.4
        and ctx.production_rate_uph > 55
    ):
        out.append(
            Contribution(
                "night_shift_load",
                "crimp_force_anomaly",
                c.param("strength", 1.3) * (ctx.tool_wear - 0.4) / 0.6,
                "shift",
                f"{ctx.line_id}:night",
            )
        )

    if (c := cfg("maintenance_effect")) is not None and ctx.days_since_maintenance < 14:
        relief = c.param("relief", 0.8)
        halflife = max(0.5, c.param("halflife_days", 3.0))
        damp = relief * math.exp(-ctx.days_since_maintenance / halflife)
        for cat in _CRIMP_CATS:
            out.append(Contribution("maintenance_effect", cat, -damp, "machine", ctx.machine_id))

    if (c := cfg("revision_shift")) is not None and ctx.revision_shifted:
        strength = c.param("strength", 1.2)
        for cat in ("crimp_height_oot", "partial_insertion"):
            out.append(
                Contribution(
                    "revision_shift",
                    cat,
                    strength * 0.7,
                    "revision",
                    f"{ctx.product_id}:{ctx.revision}",
                )
            )

    return out


def category_logits(
    ctx: UnitContext, profile: Profile
) -> tuple[dict[str, float], list[Contribution]]:
    base = base_logit(profile)
    logits = dict.fromkeys(CATEGORIES, base)
    contribs = contributions(ctx, profile)
    for c in contribs:
        logits[c.category] += c.delta_logit
    return logits, contribs


def probability(logit: float) -> float:
    return 1.0 / (1.0 + math.exp(-logit))
