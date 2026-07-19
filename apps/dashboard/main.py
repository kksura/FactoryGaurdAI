"""Streamlit dashboard (spec §19): `make dashboard`.

Reads evaluation reports and, when artifacts exist, runs an in-process
demo prediction. Serving mode is displayed prominently; assistant text is
always advisory-marked. No secrets or tokens are ever displayed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="FactoryGuard AI", page_icon="🛡️", layout="wide")
st.title("FactoryGuard AI — defect-risk platform")
st.caption(
    "Advisory system: scores and recommendations inform humans; nothing here controls machinery."
)

PROFILES = [p.name for p in Path("reports/evaluation").glob("*") if p.is_dir()] or ["small"]
profile = st.sidebar.selectbox("Dataset profile", sorted(PROFILES))
metrics_path = Path(f"reports/evaluation/{profile}/multimodal-metrics.json")


@st.cache_data
def load_metrics(path: str) -> dict | None:
    p = Path(path)
    return json.loads(p.read_text()) if p.is_file() else None


metrics = load_metrics(str(metrics_path))
if metrics is None:
    st.warning(
        f"No multimodal evaluation for `{profile}` yet — run "
        f"`make train-multimodal PROFILE={profile}`."
    )
    st.stop()

mode = metrics["serving"]["configured_mode"]
st.sidebar.metric("Serving mode", mode)
st.sidebar.caption(
    "anomaly-only = no labels yet · blended = transitioning · supervised = "
    "calibrated probabilities (ADR-0019)"
)

tab_overview, tab_uncertainty, tab_causes, tab_predict = st.tabs(
    ["Model health", "Uncertainty & abstention", "Root cause & retrieval", "Demo prediction"]
)

with tab_overview:
    st.subheader("Fusion performance (test period)")
    lf = metrics["fusion"]["late"].get("test", {})
    ef = metrics["fusion"]["embedding"].get("test", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Late fusion ROC-AUC", f"{lf.get('roc_auc', float('nan')):.3f}")
    c2.metric("Embedding fusion ROC-AUC", f"{ef.get('roc_auc', float('nan')):.3f}")
    c3.metric("Fused Brier", f"{lf.get('brier', float('nan')):.4f}")
    c4.metric("Prevalence", f"{lf.get('prevalence', float('nan')):.1%}")

    st.subheader("Per-modality (calibrated, test)")
    rows = []
    for m, v in metrics["modalities"].items():
        t = v.get("test", {})
        rows.append(
            {
                "modality": m,
                "availability": v.get("availability_test"),
                "roc_auc": t.get("roc_auc"),
                "pr_auc": t.get("pr_auc"),
                "brier": t.get("brier"),
                "ece": t.get("ece"),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True)

    st.subheader("Missing-modality robustness (ROC-AUC with one modality dropped)")
    mm = metrics["fusion"]["missing_modality"]
    st.dataframe(
        pd.DataFrame([{"dropped": k, **v} for k, v in mm.items()]),
        hide_index=True,
    )

with tab_uncertainty:
    unc = metrics["uncertainty"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Target coverage", f"{unc['target_coverage']:.0%}")
    c2.metric("Empirical coverage", f"{unc['empirical_coverage']:.1%}")
    c3.metric("Abstention rate", f"{unc['abstention_rate']:.1%}")
    c4.metric("OOD rate (test)", f"{unc['ood_rate_test']:.1%}")
    st.subheader("Risk–coverage curve")
    curve = pd.DataFrame(unc["risk_coverage"])
    st.line_chart(curve.set_index("coverage")[["error_rate", "defect_recall"]])
    st.caption(
        "Retaining only the most-confident predictions lowers the error rate — "
        "the operational argument for abstention."
    )

with tab_causes:
    rc = metrics["root_cause"]
    if rc.get("n_evaluated_units"):
        c1, c2, c3 = st.columns(3)
        c1.metric("Top-3 accuracy", f"{rc['hit_at_3']:.1%}")
        c2.metric("Top-5 accuracy", f"{rc['hit_at_5']:.1%}")
        c3.metric("MRR", f"{rc['mrr']:.3f}")
        st.caption(
            f"Evaluated on {int(rc['n_evaluated_units'])} defective test units "
            "against the generator's entity-attributed ground truth. Rankings "
            "are statistical association, not causal proof."
        )
    retr = metrics["retrieval"]
    st.subheader("Similar-incident retrieval")
    st.metric(
        f"precision@{retr['k']} (same defect category)",
        f"{retr['precision_at_k']:.3f}",
        delta=f"{retr['precision_at_k'] - retr['random_baseline']:+.3f} vs random",
    )

with tab_predict:
    st.subheader("In-process demo prediction")
    artifacts = Path(f"artifacts/multimodal/{profile}")
    if not artifacts.is_dir():
        st.info(f"No artifacts for `{profile}` — run the training pipeline first.")
    else:

        @st.cache_resource
        def load_service(path: str, prof: str):  # type: ignore[no-untyped-def]
            from factoryguard.inference.service import ArtifactBundle, PredictionService
            from factoryguard.inference.serving import ServingMode

            bundle = ArtifactBundle.load(Path(path))
            return PredictionService(
                bundle,
                serving_mode=ServingMode(mode),
                storage_root=Path("data") / prof,
            )

        units_path = Path(f"data/{profile}/tables/units.parquet")
        sensors_path = Path(f"data/{profile}/timeseries/sensors.parquet")
        if not units_path.is_file():
            st.info(f"Dataset `{profile}` not generated locally.")
        else:
            units = pd.read_parquet(units_path)
            unit_id = st.selectbox("Unit", units["unit_id"].tail(200).tolist())
            if st.button("Score unit"):
                from factoryguard.contracts.v1 import (
                    PredictionRequest,
                    ProcessMeasurements,
                    SensorSequences,
                    UnitContext,
                )

                row = units[units.unit_id == unit_id].iloc[0]
                sensors = pd.read_parquet(sensors_path)
                sub = sensors[sensors.unit_id == unit_id]
                channels = {
                    ch: [None if pd.isna(v) else float(v) for v in grp.sort_values("t")["value"]]
                    for ch, grp in sub.groupby("channel")
                }
                req = PredictionRequest(
                    unit=UnitContext(
                        unit_id=str(row.unit_id),
                        work_order_id=str(row.work_order_id),
                        plant_id=str(row.plant_id),
                        line_id=str(row.line_id),
                        machine_id=str(row.machine_id),
                        tool_id=str(row.tool_id),
                        operator_id=str(row.operator_id),
                        product_id=str(row.product_id),
                        revision=str(row.revision),
                        family=str(row.family),
                        shift=str(row["shift"]),  # .shift is a pandas method
                        terminal_lot_id=str(row.terminal_lot_id),
                        wire_lot_id=str(row.wire_lot_id),
                        produced_at=pd.Timestamp(row.produced_at).to_pydatetime(),
                    ),
                    measurements=ProcessMeasurements(
                        cycle_time_s=float(row.cycle_time_s),
                        production_rate_uph=float(row.production_rate_uph),
                        crimp_height_setpoint_mm=float(row.crimp_height_setpoint_mm),
                        crimp_height_mm=float(row.crimp_height_mm),
                        pull_force_n=float(row.pull_force_n),
                        ambient_temp_c=float(row.ambient_temp_c),
                        humidity_pct=float(row.humidity_pct),
                        tool_age_cycles=float(row.tool_age_cycles),
                        days_since_maintenance=float(row.days_since_maintenance),
                        changeover_minutes=float(row.changeover_minutes),
                        units_since_changeover=float(row.units_since_changeover),
                        recent_defect_count_line=float(row.recent_defect_count_line),
                    ),
                    sensors=SensorSequences(channels=channels) if channels else None,
                )
                svc = load_service(str(artifacts), profile)
                resp = svc.predict(req)
                c1, c2, c3 = st.columns(3)
                c1.metric(
                    "Risk score",
                    f"{resp.risk_score:.3f}",
                    help="Calibrated probability only in supervised mode.",
                )
                c2.metric("Serving mode", resp.serving_mode)
                c3.metric("Abstained", "yes" if resp.abstained else "no")
                if resp.assistant:
                    st.info(
                        f"**Assistant summary** *(generated, advisory — "
                        f"{resp.assistant.generator})*\n\n{resp.assistant.text}"
                    )
                if resp.root_causes:
                    st.subheader("Root-cause hypotheses")
                    st.dataframe(
                        pd.DataFrame([rc.model_dump() for rc in resp.root_causes]),
                        hide_index=True,
                    )
                if resp.recommendations:
                    st.subheader("Recommendations")
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "action": r.action,
                                    "severity": r.severity,
                                    "status": r.status,
                                    "policy": r.policy_id,
                                    "reason": r.reason,
                                }
                                for r in resp.recommendations
                            ]
                        ),
                        hide_index=True,
                    )
                if resp.similar_incidents:
                    st.subheader("Similar historical incidents")
                    st.dataframe(
                        pd.DataFrame([s.model_dump() for s in resp.similar_incidents]),
                        hide_index=True,
                    )
                with st.expander("Full response JSON"):
                    st.json(json.loads(resp.model_dump_json()))
