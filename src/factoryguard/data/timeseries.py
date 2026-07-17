"""Sensor time-series generation.

Per unit: a crimp-force waveform plus auxiliary machine channels for the
crimp cycle. Signals reflect the same latent state that drives labels
(tool wear widens/lowers the force peak, calibration offset shifts it, bad
terminal lots add deformation ripple), plus realistic nuisances: noise,
drift, dropout (NaN gaps), clipping, phase shift.

Output is long-format Parquet: unit_id, channel, t, value(float32).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factoryguard.data.profiles import Profile
from factoryguard.utilities.seeding import derive_seed, stable_hash

_SENSOR_MAX_FORCE = 1.6  # clipping ceiling (normalized units)


def crimp_force_waveform(
    n: int,
    rng: np.random.Generator,
    tool_wear: float,
    offset_mm: float,
    bad_lot: bool,
    sensor_bias: float,
    dropout_rate: float,
) -> np.ndarray:
    """One normalized crimp-force curve: rise, peak, release."""
    t = np.linspace(0.0, 1.0, n)
    center = 0.45 + 0.06 * offset_mm / 0.08  # calibration shifts the peak position
    width = 0.10 + 0.05 * max(0.0, tool_wear - 0.4)  # worn tools widen the peak
    peak = 1.0 - 0.25 * max(0.0, tool_wear - 0.5) / 0.5  # …and lower peak force
    phase = rng.normal(0, 0.01)
    y = peak * np.exp(-((t - center - phase) ** 2) / (2 * width**2))
    y += 0.12 * np.exp(-((t - 0.15) ** 2) / (2 * 0.04**2))  # touch-down bump
    if bad_lot:
        # deformation ripple superposed near the peak
        y += 0.06 * np.sin(2 * np.pi * 14 * t) * np.exp(-((t - center) ** 2) / (2 * 0.08**2))
    y += rng.normal(0, 0.015, n)  # measurement noise
    y += sensor_bias  # slow sensor drift (concealment mechanism)
    y = np.clip(y, 0.0, _SENSOR_MAX_FORCE)  # sensor clipping
    if dropout_rate > 0:
        mask = rng.uniform(size=n) < dropout_rate
        if mask.any():
            y = y.copy()
            y[mask] = np.nan  # sensor dropout
    return y.astype(np.float32)


def aux_channel(
    channel: str, n: int, rng: np.random.Generator, tool_wear: float, dropout_rate: float
) -> np.ndarray:
    t = np.linspace(0.0, 1.0, n)
    if channel == "motor_current":
        y = 0.5 + 0.35 * np.sin(np.pi * t) + 0.1 * max(0.0, tool_wear - 0.5)
        y += rng.normal(0, 0.02, n)
    elif channel == "vibration":
        base = 0.05 + 0.20 * max(0.0, tool_wear - 0.45)
        y = base * np.abs(rng.normal(0, 1, n)) + 0.02 * np.sin(2 * np.pi * 30 * t)
    elif channel == "temperature":
        y = 0.4 + 0.05 * t + rng.normal(0, 0.005, n)
    elif channel == "pressure":
        y = 0.6 + 0.1 * np.sin(np.pi * t) + rng.normal(0, 0.01, n)
    else:
        y = rng.normal(0, 0.05, n)
    if dropout_rate > 0:
        mask = rng.uniform(size=n) < dropout_rate
        y = y.copy()
        y[mask] = np.nan
    return y.astype(np.float32)


def generate_timeseries(units: pd.DataFrame, profile: Profile) -> pd.DataFrame:
    """Long-format sensor table for all units (crimp force + aux channels)."""
    ts_cfg = profile.timeseries
    frames: list[pd.DataFrame] = []
    drift_cfg = profile.mechanisms.get("sensor_drift")
    drift_per_day = (
        drift_cfg.param("drift_per_day", 0.002) if drift_cfg and drift_cfg.enabled else 0.0
    )
    start_day = profile.date_range.start

    for row in units.itertuples():
        rng = np.random.default_rng(derive_seed(profile.seed, "timeseries", row.unit_id))
        days_elapsed = (row.produced_at.date() - start_day).days
        sensor_bias = (
            drift_per_day * days_elapsed * (1.0 if stable_hash(row.machine_id, mod=3) == 0 else 0.0)
        )
        wear_proxy = min(1.2, row.tool_age_cycles / 120_000 + 0.2)
        offset = float(row.crimp_height_mm) - float(row.crimp_height_setpoint_mm)
        force = crimp_force_waveform(
            ts_cfg.crimp_force_points,
            rng,
            tool_wear=wear_proxy,
            offset_mm=float(np.clip(offset, -0.12, 0.12)),
            bad_lot=bool(row.pull_force_n < 80),
            sensor_bias=sensor_bias,
            dropout_rate=ts_cfg.sensor_dropout_rate,
        )
        channels = {"crimp_force": force}
        for ch in ts_cfg.aux_channels:
            channels[ch] = aux_channel(
                ch, ts_cfg.aux_points, rng, wear_proxy, ts_cfg.sensor_dropout_rate
            )
        for ch, values in channels.items():
            frames.append(
                pd.DataFrame(
                    {
                        "unit_id": row.unit_id,
                        "channel": ch,
                        "t": np.arange(len(values), dtype=np.int32),
                        "value": values,
                    }
                )
            )
    if not frames:
        return pd.DataFrame(columns=["unit_id", "channel", "t", "value"])
    return pd.concat(frames, ignore_index=True)
