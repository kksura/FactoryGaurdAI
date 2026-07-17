"""Static synthetic world: plants, lines, machines, tools, operators,
suppliers, components, material lots, products, BOM, and routing.

Everything is deterministic for a given profile (seeded via derive_seed
scopes) and internally consistent: every foreign key resolves.

Latent truth (bad lots, calibration offsets, shifted revisions) is kept in
separate "latent" tables that the training pipeline must never read; they
exist to evaluate root-cause ranking against ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from factoryguard.data.profiles import Profile
from factoryguard.utilities.seeding import rng_for

ROUTING_STEPS = [
    "wire_cut",
    "strip",
    "crimp",
    "seal_insert",
    "connector_assembly",
    "taping",
    "vision_inspection",
    "continuity_test",
    "eol_inspection",
]

COMPONENT_TYPES = ("connector", "terminal", "wire", "seal")

SHIFTS = ("day", "evening", "night")


@dataclass
class World:
    plants: pd.DataFrame
    lines: pd.DataFrame
    machines: pd.DataFrame
    tools: pd.DataFrame
    operators: pd.DataFrame
    suppliers: pd.DataFrame
    components: pd.DataFrame
    material_lots: pd.DataFrame
    products: pd.DataFrame
    revisions: pd.DataFrame
    bom_edges: pd.DataFrame
    routing: pd.DataFrame
    # Latent truth — never features. Written under ground_truth/ only.
    latent_machine_offsets: pd.DataFrame = field(default_factory=pd.DataFrame)
    latent_bad_lots: pd.DataFrame = field(default_factory=pd.DataFrame)
    latent_shifted_revisions: pd.DataFrame = field(default_factory=pd.DataFrame)
    latent_camera_windows: pd.DataFrame = field(default_factory=pd.DataFrame)
    weather: pd.DataFrame = field(default_factory=pd.DataFrame)  # observable

    def tables(self) -> dict[str, pd.DataFrame]:
        """Public (non-latent) tables keyed by output file name."""
        return {
            "plants": self.plants,
            "lines": self.lines,
            "machines": self.machines,
            "tools": self.tools,
            "operators": self.operators,
            "suppliers": self.suppliers,
            "components": self.components,
            "material_lots": self.material_lots,
            "products": self.products,
            "revisions": self.revisions,
            "bom_edges": self.bom_edges,
            "routing": self.routing,
            "weather": self.weather,
        }

    def latent_tables(self) -> dict[str, pd.DataFrame]:
        return {
            "latent_machine_offsets": self.latent_machine_offsets,
            "latent_bad_lots": self.latent_bad_lots,
            "latent_shifted_revisions": self.latent_shifted_revisions,
            "latent_camera_windows": self.latent_camera_windows,
        }


def build_world(profile: Profile) -> World:
    seed = profile.seed
    w = profile.world

    plants = pd.DataFrame(
        {
            "plant_id": [f"PL{p + 1:02d}" for p in range(w.plants)],
            "region": [["EMEA", "AMER", "APAC"][p % 3] for p in range(w.plants)],
        }
    )

    lines = pd.DataFrame(
        [
            {"line_id": f"{pl}-L{li + 1:02d}", "plant_id": pl}
            for pl in plants["plant_id"]
            for li in range(w.lines_per_plant)
        ]
    )

    machines = pd.DataFrame(
        [
            {
                "machine_id": f"M-{line}-{m + 1:02d}",
                "line_id": line,
                "machine_type": "crimp_press",
                "commissioned": (profile.date_range.start - timedelta(days=200 + 37 * m)),
            }
            for line in lines["line_id"]
            for m in range(w.crimp_machines_per_line)
        ]
    )

    rng_tools = rng_for(seed, "world", "tools")
    tools = pd.DataFrame(
        [
            {
                "tool_id": f"T-{mid.removeprefix('M-')}-{t + 1}",
                "machine_id": mid,
                "tool_type": "crimp_applicator",
                "initial_age_cycles": int(rng_tools.integers(0, 40_000)),
            }
            for mid in machines["machine_id"]
            for t in range(2)
        ]
    )

    rng_ops = rng_for(seed, "world", "operators")
    operators = pd.DataFrame(
        [
            {
                # Pseudonymous by construction; no names anywhere (responsible AI).
                "operator_id": f"OP-{pl}-{o + 1:04d}",
                "plant_id": pl,
                "primary_shift": SHIFTS[int(rng_ops.integers(0, len(SHIFTS)))],
            }
            for pl in plants["plant_id"]
            for o in range(w.operators_per_plant)
        ]
    )

    suppliers = pd.DataFrame(
        {
            "supplier_id": [f"SUP-{s + 1:02d}" for s in range(w.suppliers)],
            "region": [["EMEA", "AMER", "APAC"][s % 3] for s in range(w.suppliers)],
        }
    )

    # Components: per family one connector type; terminals/wires/seals shared pool.
    rng_comp = rng_for(seed, "world", "components")
    comp_rows: list[dict[str, object]] = []
    n_terminals = max(2, w.product_families)
    n_wires = max(2, w.product_families)
    n_seals = max(2, w.product_families - 1)
    for i in range(w.product_families):
        comp_rows.append({"component_id": f"CON-{i + 1:03d}", "component_type": "connector"})
    for i in range(n_terminals):
        comp_rows.append({"component_id": f"TER-{i + 1:03d}", "component_type": "terminal"})
    for i in range(n_wires):
        comp_rows.append({"component_id": f"WIR-{i + 1:03d}", "component_type": "wire"})
    for i in range(n_seals):
        comp_rows.append({"component_id": f"SEA-{i + 1:03d}", "component_type": "seal"})
    components = pd.DataFrame(comp_rows)
    components["supplier_id"] = [
        suppliers["supplier_id"].iloc[int(rng_comp.integers(0, len(suppliers)))]
        for _ in range(len(components))
    ]

    # Material lots per component, received across the date range.
    rng_lots = rng_for(seed, "world", "lots")
    lot_rows: list[dict[str, object]] = []
    span = profile.date_range.days
    for _, comp in components.iterrows():
        for k in range(w.material_lots_per_component):
            received = profile.date_range.start + timedelta(
                days=int(rng_lots.integers(-30, max(1, span - 10)))
            )
            lot_rows.append(
                {
                    "lot_id": f"LOT-{comp['component_id']}-{k + 1:04d}",
                    "component_id": comp["component_id"],
                    "component_type": comp["component_type"],
                    "supplier_id": comp["supplier_id"],
                    "received_date": received,
                }
            )
    material_lots = pd.DataFrame(lot_rows)

    # Products and revisions.
    prod_rows = []
    rev_rows = []
    for f in range(w.product_families):
        family = f"PF-{chr(ord('A') + f)}"
        for p in range(w.products_per_family):
            pid = f"HRN-{f + 1}{p + 1:03d}"
            prod_rows.append(
                {
                    "product_id": pid,
                    "family": family,
                    "connector_id": f"CON-{f + 1:03d}",
                    "has_seal": bool((f + p) % 2 == 0),
                }
            )
            for rev in ["A", "B"] if p % 2 == 0 else ["A"]:
                rev_rows.append({"product_id": pid, "revision": rev})
    products = pd.DataFrame(prod_rows)
    revisions = pd.DataFrame(rev_rows)

    # BOM: product -> connector -> terminal -> wire (+ seal when applicable).
    rng_bom = rng_for(seed, "world", "bom")
    bom = []
    terminals = components[components.component_type == "terminal"]["component_id"].tolist()
    wires = components[components.component_type == "wire"]["component_id"].tolist()
    seals = components[components.component_type == "seal"]["component_id"].tolist()
    for _, prod in products.iterrows():
        terminal = terminals[int(rng_bom.integers(0, len(terminals)))]
        wire = wires[int(rng_bom.integers(0, len(wires)))]
        bom.append(
            {"parent": prod["product_id"], "child": prod["connector_id"], "relation": "contains"}
        )
        bom.append({"parent": prod["connector_id"], "child": terminal, "relation": "contains"})
        bom.append({"parent": terminal, "child": wire, "relation": "connects"})
        if prod["has_seal"]:
            seal = seals[int(rng_bom.integers(0, len(seals)))]
            bom.append({"parent": prod["connector_id"], "child": seal, "relation": "contains"})
    bom_edges = pd.DataFrame(bom).drop_duplicates(ignore_index=True)

    routing = pd.DataFrame(
        [
            {"product_id": pid, "step_no": i + 1, "step": step}
            for pid in products["product_id"]
            for i, step in enumerate(ROUTING_STEPS)
        ]
    )

    # Observable weather per plant/day (humidity mechanism input).
    rng_weather = rng_for(seed, "world", "weather")
    weather_rows = []
    for pl in plants["plant_id"]:
        base_h = float(rng_weather.uniform(45, 60))
        base_t = float(rng_weather.uniform(18, 26))
        for d in range(span + 1):
            day = profile.date_range.start + timedelta(days=d)
            season = 10.0 * np.sin(2 * np.pi * (d / 90.0) + float(rng_weather.uniform(0, 1)))
            weather_rows.append(
                {
                    "plant_id": pl,
                    "day": day,
                    "humidity_pct": float(
                        np.clip(base_h + season + rng_weather.normal(0, 6), 20, 98)
                    ),
                    "ambient_temp_c": float(base_t + season / 3 + rng_weather.normal(0, 1.5)),
                }
            )
    weather = pd.DataFrame(weather_rows)

    world = World(
        plants=plants,
        lines=lines,
        machines=machines,
        tools=tools,
        operators=operators,
        suppliers=suppliers,
        components=components,
        material_lots=material_lots,
        products=products,
        revisions=revisions,
        bom_edges=bom_edges,
        routing=routing,
        weather=weather,
    )
    _assign_latent_truth(world, profile)
    return world


def _assign_latent_truth(world: World, profile: Profile) -> None:
    """Hidden causal ground truth used by mechanisms and evaluation only."""
    seed = profile.seed
    mech = profile.mechanisms

    # Bad supplier lots (terminal lots only — deformation mechanism).
    lot_cfg = mech.get("supplier_lot")
    rng = rng_for(seed, "latent", "bad_lots")
    term_lots = world.material_lots[world.material_lots.component_type == "terminal"]
    frac = lot_cfg.param("bad_lot_fraction", 0.1) if lot_cfg and lot_cfg.enabled else 0.0
    n_bad = int(round(frac * len(term_lots)))
    bad_ids = (
        rng.choice(term_lots["lot_id"].to_numpy(), size=n_bad, replace=False)
        if n_bad
        else np.array([], dtype=object)
    )
    world.latent_bad_lots = pd.DataFrame({"lot_id": sorted(map(str, bad_ids))})

    # Machine calibration offsets affecting specific product families.
    cal_cfg = mech.get("calibration_offset")
    rng = rng_for(seed, "latent", "calibration")
    rows = []
    if cal_cfg and cal_cfg.enabled:
        frac = cal_cfg.param("affected_machine_fraction", 0.15)
        n_aff = int(round(frac * len(world.machines)))
        affected = rng.choice(world.machines["machine_id"].to_numpy(), size=n_aff, replace=False)
        families = sorted(world.products["family"].unique())
        for mid in sorted(map(str, affected)):
            rows.append(
                {
                    "machine_id": mid,
                    "offset_mm": float(rng.choice([-1, 1]) * rng.uniform(0.04, 0.09)),
                    "affected_family": families[int(rng.integers(0, len(families)))],
                }
            )
    world.latent_machine_offsets = pd.DataFrame(
        rows, columns=["machine_id", "offset_mm", "affected_family"]
    )

    # Engineering revisions with shifted process baselines (revision B subset).
    rev_cfg = mech.get("revision_shift")
    rng = rng_for(seed, "latent", "revisions")
    b_revs = world.revisions[world.revisions.revision == "B"]
    frac = rev_cfg.param("shifted_revision_fraction", 0.3) if rev_cfg and rev_cfg.enabled else 0.0
    n_shift = int(round(frac * len(b_revs)))
    shifted = (
        rng.choice(b_revs["product_id"].to_numpy(), size=n_shift, replace=False)
        if n_shift
        else np.array([], dtype=object)
    )
    world.latent_shifted_revisions = pd.DataFrame(
        {"product_id": sorted(map(str, shifted)), "revision": "B"}
    )

    # Camera misalignment windows per line (image-quality drift, Scenario C).
    cam_cfg = mech.get("camera_misalignment")
    rng = rng_for(seed, "latent", "camera")
    rows = []
    if cam_cfg and cam_cfg.enabled:
        span = profile.date_range.days
        win_days = max(3, int(cam_cfg.param("window_fraction", 0.1) * span))
        # One affected line: the last line of the first plant (deterministic pick).
        affected_line = world.lines["line_id"].iloc[len(world.lines) // 2]
        start_off = int(rng.integers(span // 2, max(span // 2 + 1, span - win_days)))
        rows.append(
            {
                "line_id": affected_line,
                "start_day": profile.date_range.start + timedelta(days=start_off),
                "end_day": profile.date_range.start
                + timedelta(days=min(span, start_off + win_days)),
                "blur_sigma": cam_cfg.param("blur_sigma", 2.0),
            }
        )
    world.latent_camera_windows = pd.DataFrame(
        rows, columns=["line_id", "start_day", "end_day", "blur_sigma"]
    )


def business_day_shift(ts_hour: int) -> str:
    """Map an hour of day to a shift name."""
    if 6 <= ts_hour < 14:
        return "day"
    if 14 <= ts_hour < 22:
        return "evening"
    return "night"


def weather_lookup(weather: pd.DataFrame) -> dict[tuple[str, date], tuple[float, float]]:
    """(plant, day) -> (humidity, temp) fast lookup."""
    return {
        (str(r.plant_id), r.day): (float(r.humidity_pct), float(r.ambient_temp_c))
        for r in weather.itertuples()
    }
