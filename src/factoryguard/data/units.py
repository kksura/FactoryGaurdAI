"""Production simulation: work orders, units, process steps, labels,
maintenance events, and root-cause ground truth.

The simulation walks each line chronologically so state that must be
causal-in-time (tool wear, maintenance, changeovers, lot consumption,
sensor drift) evolves consistently with timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from factoryguard.data import mechanisms as mech
from factoryguard.data.profiles import Profile
from factoryguard.data.world import ROUTING_STEPS, World, business_day_shift, weather_lookup
from factoryguard.utilities.seeding import rng_for, stable_hash

# Minutes of changeover below which the setup is considered inadequate (latent).
_INADEQUATE_CHANGEOVER_MIN = 12.0
_WEAR_MAINTENANCE_THRESHOLD = 1.0


def _pick_lot(
    lots_by_type: dict[str, pd.DataFrame],
    kind: str,
    day: object,
    unit_seq: int,
    lot_rotation: int,
) -> str | None:
    """Deterministic lot rotation: the received lot whose index (mod pool
    size) matches the current unit sequence, restricted to lots already
    received by ``day``."""
    lots = lots_by_type[kind]
    if lots.empty:
        return None
    eligible = lots[lots.received_date <= day]
    pool = eligible if not eligible.empty else lots
    idx = (unit_seq // lot_rotation) % len(pool)
    return str(pool.iloc[idx]["lot_id"])


@dataclass
class GeneratedProduction:
    work_orders: pd.DataFrame
    units: pd.DataFrame
    step_events: pd.DataFrame
    labels: pd.DataFrame
    maintenance: pd.DataFrame
    ground_truth: pd.DataFrame


@dataclass
class _ToolState:
    tool_id: str
    wear: float
    cycles: int
    last_maintenance: datetime
    wear_rate_multiplier: float = 1.0


@dataclass
class _MachineState:
    machine_id: str
    tools: list[_ToolState]
    active_tool: int = 0
    offset_mm: float = 0.0
    offset_family: str = ""
    sensor_bias: float = 0.0

    @property
    def tool(self) -> _ToolState:
        return self.tools[self.active_tool]


@dataclass
class _LineState:
    line_id: str
    plant_id: str
    machines: list[_MachineState]
    next_machine: int = 0
    units_since_changeover: int = 0
    changeover_minutes: float = 20.0
    recent_defects: list[int] = field(default_factory=list)


def simulate_production(world: World, profile: Profile) -> GeneratedProduction:
    rng = rng_for(profile.seed, "production")
    lots_by_type = {
        t: world.material_lots[world.material_lots.component_type == t].sort_values("received_date")
        for t in ("terminal", "wire", "seal")
    }
    bad_lots = set(world.latent_bad_lots["lot_id"].tolist())
    shifted_revs = {(r.product_id, r.revision) for r in world.latent_shifted_revisions.itertuples()}
    offsets = {
        r.machine_id: (float(r.offset_mm), str(r.affected_family))
        for r in world.latent_machine_offsets.itertuples()
    }
    weather = weather_lookup(world.weather)
    prod_info = world.products.set_index("product_id")
    revs_by_product: dict[str, list[str]] = (
        world.revisions.groupby("product_id")["revision"].apply(list).to_dict()
    )
    ops_by_plant: dict[str, dict[str, list[str]]] = {}
    for r in world.operators.itertuples():
        ops_by_plant.setdefault(r.plant_id, {}).setdefault(r.primary_shift, []).append(
            r.operator_id
        )

    line_states: list[_LineState] = []
    for line in world.lines.itertuples():
        machines = []
        for m in world.machines[world.machines.line_id == line.line_id].itertuples():
            tools = [
                _ToolState(
                    tool_id=t.tool_id,
                    wear=min(0.9, t.initial_age_cycles / 120_000),
                    cycles=t.initial_age_cycles,
                    last_maintenance=datetime.combine(
                        profile.date_range.start, datetime.min.time(), tzinfo=UTC
                    )
                    - timedelta(days=int(rng.integers(1, 30))),
                    # Per-tool wear-rate variation (lognormal, seeded by tool_id):
                    # without this every tool on every machine wears at an
                    # identical rate and all machines cross the maintenance
                    # threshold in lockstep near the end of the date range,
                    # which starves train of any high-wear examples and puts
                    # them all in val/calib/test (a temporal-split artifact
                    # that made HGB generalize at chance on `medium`).
                    wear_rate_multiplier=float(
                        np.clip(
                            rng_for(profile.seed, "tool_wear_rate", t.tool_id).lognormal(
                                mean=0.0, sigma=0.35
                            ),
                            0.4,
                            2.2,
                        )
                    ),
                )
                for t in world.tools[world.tools.machine_id == m.machine_id].itertuples()
            ]
            off_mm, off_family = offsets.get(m.machine_id, (0.0, ""))
            machines.append(
                _MachineState(m.machine_id, tools, offset_mm=off_mm, offset_family=off_family)
            )
        line_states.append(_LineState(line.line_id, line.plant_id, machines))

    n_units = profile.production.units
    n_lines = len(line_states)
    span_days = profile.date_range.days
    units_per_line = n_units // n_lines + 1
    per_day = max(1, units_per_line // max(1, span_days))
    minutes_between = max(4.0, (16 * 60) / (per_day + 1))

    drift_cfg = profile.mechanisms.get("sensor_drift")
    drift_per_day = (
        drift_cfg.param("drift_per_day", 0.002) if drift_cfg and drift_cfg.enabled else 0.0
    )
    products = world.products["product_id"].tolist()
    base_start = datetime.combine(profile.date_range.start, datetime.min.time(), tzinfo=UTC)

    wo_rows, unit_rows, step_rows, label_rows, maint_rows, gt_rows = [], [], [], [], [], []
    unit_seq = 0
    wo_seq = 0

    for ls in line_states:
        clock = base_start + timedelta(hours=6, minutes=float(rng.uniform(0, 30)))
        produced = 0
        while produced < units_per_line and unit_seq < n_units:
            # --- new work order (product + revision + changeover) ---
            wo_seq += 1
            wo_id = f"WO-{wo_seq:06d}"
            product_id = products[int(rng.integers(0, len(products)))]
            revision = revs_by_product[product_id][
                int(rng.integers(0, len(revs_by_product[product_id])))
            ]
            changeover_min = float(np.clip(rng.lognormal(np.log(18), 0.5), 4, 90))
            ls.changeover_minutes = changeover_min
            ls.units_since_changeover = 0
            clock += timedelta(minutes=changeover_min)
            wo_rows.append(
                {
                    "work_order_id": wo_id,
                    "line_id": ls.line_id,
                    "product_id": product_id,
                    "revision": revision,
                    "changeover_minutes": round(changeover_min, 1),
                    "started_at": clock,
                }
            )
            wo_units = min(
                profile.production.units_per_work_order,
                units_per_line - produced,
                n_units - unit_seq,
            )
            has_seal = bool(prod_info.loc[product_id, "has_seal"])
            family = str(prod_info.loc[product_id, "family"])
            setpoint = 1.8 + 0.1 * stable_hash(product_id, mod=8)  # deterministic per product

            for _k in range(wo_units):
                unit_seq += 1
                produced += 1
                ls.units_since_changeover += 1
                unit_id = f"UNIT-{unit_seq:07d}"
                machine = ls.machines[ls.next_machine]
                ls.next_machine = (ls.next_machine + 1) % len(ls.machines)
                # Round-robin the provisioned tools so both accumulate wear
                # and reach maintenance on staggered schedules, rather than
                # always using tool index 0.
                machine.active_tool = (machine.active_tool + 1) % len(machine.tools)
                tool = machine.tool

                # advance clock; roll to next morning after ~22:00 sometimes
                clock += timedelta(minutes=minutes_between * float(rng.uniform(0.7, 1.3)))
                if clock.hour >= 22 and rng.uniform() < 0.6:
                    clock = (clock + timedelta(days=1)).replace(
                        hour=6, minute=int(rng.integers(0, 59))
                    )
                day = clock.date()
                if day > profile.date_range.end:
                    day = profile.date_range.end
                shift = business_day_shift(clock.hour)
                humidity, temp = weather.get((ls.plant_id, day), (55.0, 22.0))

                # tool wear & maintenance
                wear_cfg = profile.mechanisms.get("tool_wear")
                wear_rate = (
                    wear_cfg.param("wear_per_cycle", 0.001)
                    if wear_cfg and wear_cfg.enabled
                    else 0.0
                )
                tool.wear += wear_rate * tool.wear_rate_multiplier * float(rng.uniform(0.7, 1.4))
                tool.cycles += 1
                if tool.wear >= _WEAR_MAINTENANCE_THRESHOLD:
                    maint_rows.append(
                        {
                            "maintenance_id": f"MNT-{len(maint_rows) + 1:05d}",
                            "machine_id": machine.machine_id,
                            "tool_id": tool.tool_id,
                            "performed_at": clock,
                            "kind": "tool_replacement",
                        }
                    )
                    tool.wear = 0.05
                    tool.last_maintenance = clock
                    # A tool_replacement installs a physically new applicator:
                    # its lifetime cycle counter resets too. Without this,
                    # tool_age_cycles and days_since_maintenance are unbounded
                    # monotonic proxies for elapsed calendar time — a tree
                    # model trained on an early time window then cannot
                    # extrapolate to the larger values seen later, collapsing
                    # test-period ROC-AUC to chance regardless of true signal.
                    tool.cycles = int(rng.integers(0, 500))

                days_since_maint = (clock - tool.last_maintenance).total_seconds() / 86400.0

                # material lots: rotate deterministically through received
                # lots so every received lot sees use within the run.
                lot_rotation = max(15, n_units // 16)
                terminal_lot = (
                    _pick_lot(lots_by_type, "terminal", day, unit_seq, lot_rotation)
                    or "LOT-UNKNOWN"
                )
                wire_lot = (
                    _pick_lot(lots_by_type, "wire", day, unit_seq, lot_rotation) or "LOT-UNKNOWN"
                )
                seal_lot = (
                    _pick_lot(lots_by_type, "seal", day, unit_seq, lot_rotation)
                    if has_seal
                    else None
                )

                cal_offset = machine.offset_mm if machine.offset_family == family else 0.0
                rate_uph = float(np.clip(60 / minutes_between * 60, 20, 90))
                if shift == "night":
                    rate_uph *= 1.1

                ctx = mech.UnitContext(
                    tool_wear=tool.wear,
                    tool_id=tool.tool_id,
                    machine_id=machine.machine_id,
                    line_id=ls.line_id,
                    plant_id=ls.plant_id,
                    shift=shift,
                    terminal_lot_id=terminal_lot,
                    terminal_lot_is_bad=terminal_lot in bad_lots,
                    humidity_pct=humidity,
                    product_has_seal=has_seal,
                    calibration_offset_mm=cal_offset,
                    is_first_piece_after_changeover=(
                        ls.units_since_changeover
                        <= int(
                            profile.mechanisms.get("changeover").param("first_pieces", 5)
                            if profile.mechanisms.get("changeover")
                            else 5
                        )
                    ),
                    changeover_inadequate=changeover_min < _INADEQUATE_CHANGEOVER_MIN,
                    work_order_id=wo_id,
                    days_since_maintenance=days_since_maint,
                    production_rate_uph=rate_uph,
                    revision_shifted=(product_id, revision) in shifted_revs,
                    product_id=product_id,
                    revision=revision,
                )
                logits, contribs = mech.category_logits(ctx, profile)

                # sample defect outcome per category
                fired: list[str] = [
                    cat for cat, lg in logits.items() if rng.uniform() < mech.probability(lg)
                ]
                failed = bool(fired)
                if failed:
                    fired.sort(key=lambda c: logits[c], reverse=True)
                    category = fired[0]
                    severity = mech.SEVERITY[category]
                else:
                    category, severity = "none", "none"

                # measured process values (true + sensor effects)
                days_elapsed = (day - profile.date_range.start).days
                machine.sensor_bias = (
                    drift_per_day
                    * days_elapsed
                    * (1.0 if stable_hash(machine.machine_id, mod=3) == 0 else 0.0)
                )
                true_height = (
                    setpoint
                    + cal_offset
                    + 0.06 * max(0.0, tool.wear - 0.5)
                    + float(rng.normal(0, 0.012))
                )
                observed_height = true_height + machine.sensor_bias
                pull_force = float(
                    np.clip(
                        95
                        - 28 * max(0.0, tool.wear - 0.4)
                        - (9.0 if terminal_lot in bad_lots else 0.0)
                        + rng.normal(0, 2.5),
                        30,
                        130,
                    )
                )
                cycle_s = float(np.clip(rng.normal(minutes_between * 60 * 0.45, 4), 15, 600))

                unit_rows.append(
                    {
                        "unit_id": unit_id,
                        "work_order_id": wo_id,
                        "product_id": product_id,
                        "revision": revision,
                        "family": family,
                        "plant_id": ls.plant_id,
                        "line_id": ls.line_id,
                        "machine_id": machine.machine_id,
                        "tool_id": tool.tool_id,
                        "operator_id": _pick_operator(ops_by_plant, ls.plant_id, shift, rng),
                        "shift": shift,
                        "terminal_lot_id": terminal_lot,
                        "wire_lot_id": wire_lot,
                        "seal_lot_id": seal_lot,
                        "produced_at": clock,
                        "cycle_time_s": round(cycle_s, 1),
                        "production_rate_uph": round(rate_uph, 1),
                        "crimp_height_setpoint_mm": round(setpoint, 3),
                        "crimp_height_mm": round(observed_height, 4),
                        "pull_force_n": round(pull_force, 2),
                        "ambient_temp_c": round(temp, 1),
                        "humidity_pct": round(humidity, 1),
                        "tool_age_cycles": tool.cycles,
                        "cycles_since_maintenance": int(
                            max(0.0, days_since_maint) * per_day * minutes_between / 10
                        ),
                        "days_since_maintenance": round(days_since_maint, 2),
                        "changeover_minutes": round(changeover_min, 1),
                        "units_since_changeover": ls.units_since_changeover,
                        "recent_defect_count_line": sum(ls.recent_defects[-50:]),
                    }
                )
                ls.recent_defects.append(int(failed))

                # process step events
                t = clock
                for i, step in enumerate(ROUTING_STEPS):
                    step_rows.append(
                        {
                            "unit_id": unit_id,
                            "step_no": i + 1,
                            "step": step,
                            "started_at": t,
                        }
                    )
                    t += timedelta(seconds=cycle_s / len(ROUTING_STEPS))

                # label (with optional noise + delay)
                observed_failed = failed
                if rng.uniform() < profile.labels.label_noise_rate:
                    observed_failed = not observed_failed
                label_rows.append(
                    {
                        "unit_id": unit_id,
                        "failed_eol": observed_failed,
                        "defect_category": category
                        if observed_failed and failed
                        else ("none" if not observed_failed else category),
                        "severity": severity if observed_failed and failed else "none",
                        "labeled_at": clock + timedelta(days=profile.labels.label_delay_days),
                    }
                )

                if failed:
                    relevant = sorted(
                        (c for c in contribs if c.category == category and c.delta_logit > 0),
                        key=lambda c: c.delta_logit,
                        reverse=True,
                    )
                    for rank, c in enumerate(relevant, start=1):
                        gt_rows.append(
                            {
                                "unit_id": unit_id,
                                "rank": rank,
                                "mechanism": c.mechanism,
                                "entity_type": c.entity_type,
                                "entity_id": c.entity_id,
                                "delta_logit": round(c.delta_logit, 4),
                                "category": category,
                            }
                        )

    return GeneratedProduction(
        work_orders=pd.DataFrame(wo_rows),
        units=pd.DataFrame(unit_rows),
        step_events=pd.DataFrame(step_rows),
        labels=pd.DataFrame(label_rows),
        maintenance=pd.DataFrame(
            maint_rows,
            columns=["maintenance_id", "machine_id", "tool_id", "performed_at", "kind"],
        ),
        ground_truth=pd.DataFrame(
            gt_rows,
            columns=[
                "unit_id",
                "rank",
                "mechanism",
                "entity_type",
                "entity_id",
                "delta_logit",
                "category",
            ],
        ),
    )


def _pick_operator(
    ops_by_plant: dict[str, dict[str, list[str]]],
    plant_id: str,
    shift: str,
    rng: np.random.Generator,
) -> str:
    pool = ops_by_plant.get(plant_id, {}).get(shift) or [
        op for shift_ops in ops_by_plant.get(plant_id, {}).values() for op in shift_ops
    ]
    return pool[int(rng.integers(0, len(pool)))]
