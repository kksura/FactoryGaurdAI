"""Graph relationship edges derived from the generated tables.

Typed edge list persisted as Parquet; NetworkX graphs are built on demand
by the feature pipeline (ADR-0007). Edges carry timestamps where the
relationship is time-bound so downstream features can respect temporal
cutoffs and avoid leakage.
"""

from __future__ import annotations

import pandas as pd

from factoryguard.data.units import GeneratedProduction
from factoryguard.data.world import World


def build_edges(world: World, prod: GeneratedProduction) -> pd.DataFrame:
    edges: list[dict[str, object]] = []

    def add(src: object, dst: object, relation: str, ts: object = None) -> None:
        edges.append({"src": str(src), "dst": str(dst), "relation": relation, "ts": ts})

    for r in world.lines.itertuples():
        add(r.plant_id, r.line_id, "plant_has_line")
    for r in world.machines.itertuples():
        add(r.line_id, r.machine_id, "line_has_machine")
    for r in world.tools.itertuples():
        add(r.machine_id, r.tool_id, "machine_uses_tool")
    for r in world.components.itertuples():
        add(r.supplier_id, r.component_id, "supplier_supplies")
    for r in world.material_lots.itertuples():
        add(r.component_id, r.lot_id, "component_has_lot")
        add(r.supplier_id, r.lot_id, "supplier_supplied_lot")
    for r in world.bom_edges.itertuples():
        add(r.parent, r.child, f"bom_{r.relation}")

    units = prod.units
    for r in units.itertuples():
        add(r.unit_id, r.product_id, "unit_of_product", r.produced_at)
        add(r.unit_id, r.machine_id, "unit_processed_by", r.produced_at)
        add(r.unit_id, r.tool_id, "unit_used_tool", r.produced_at)
        add(r.unit_id, r.operator_id, "unit_run_by", r.produced_at)
        add(r.unit_id, r.terminal_lot_id, "unit_consumed_lot", r.produced_at)
        add(r.unit_id, r.wire_lot_id, "unit_consumed_lot", r.produced_at)
        if r.seal_lot_id is not None and isinstance(r.seal_lot_id, str):
            add(r.unit_id, r.seal_lot_id, "unit_consumed_lot", r.produced_at)

    failed = prod.labels[prod.labels.failed_eol]
    cat = failed.set_index("unit_id")["defect_category"].to_dict()
    ts_by_unit = units.set_index("unit_id")["produced_at"].to_dict()
    for unit_id, category in cat.items():
        add(unit_id, f"DEFECT:{category}", "unit_has_defect", ts_by_unit.get(unit_id))

    for r in prod.maintenance.itertuples():
        add(r.maintenance_id, r.machine_id, "maintenance_on_machine", r.performed_at)
        add(r.maintenance_id, r.tool_id, "maintenance_on_tool", r.performed_at)

    return pd.DataFrame(edges, columns=["src", "dst", "relation", "ts"])
