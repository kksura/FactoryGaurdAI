"""Statistical time-series anomaly detector (Phase 3 baseline; also the
`anomaly-only` cold-start TS scorer, ADR-0019).

Reference envelope per channel/timestep = median ± MAD over the *training
period* waveforms (labels unused — contamination-tolerant robust stats).
Unit score combines the worst robust z-excursion with crimp-force shape
features (peak height/position/width deviation from reference).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

_EPS = 1e-9
_Z_CAP = 12.0


@dataclass
class ChannelEnvelope:
    median: np.ndarray
    mad: np.ndarray


def _pivot(sensors: pd.DataFrame, channel: str) -> pd.DataFrame:
    """unit_id × t value matrix for one channel (NaN where dropout)."""
    sub = sensors[sensors.channel == channel]
    return sub.pivot_table(index="unit_id", columns="t", values="value", dropna=False)


def _shape_features(wave: np.ndarray) -> np.ndarray:
    """peak height, peak position (fraction), width above half max (fraction)."""
    if np.all(np.isnan(wave)):
        return np.array([np.nan, np.nan, np.nan])
    filled = np.where(np.isnan(wave), np.nanmin(wave), wave)
    peak = float(np.max(filled))
    pos = float(np.argmax(filled)) / max(1, len(filled) - 1)
    half = peak / 2
    width = float(np.mean(filled >= half))
    return np.array([peak, pos, width])


class StatTsDetector:
    name = "stat_ts_detector"

    def __init__(self, channels: list[str] | None = None) -> None:
        self.channels = channels  # None = all channels present at fit time
        self.envelopes: dict[str, ChannelEnvelope] = {}
        self.shape_ref: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._score_scale: float = 1.0

    def fit(self, sensors: pd.DataFrame, train_unit_ids: pd.Index | list[str]) -> StatTsDetector:
        train = sensors[sensors.unit_id.isin(set(train_unit_ids))]
        channels = self.channels or sorted(train["channel"].unique())
        self.channels = channels
        for ch in channels:
            mat = _pivot(train, ch).to_numpy(dtype=float)
            med = np.nanmedian(mat, axis=0)
            mad = np.nanmedian(np.abs(mat - med), axis=0) * 1.4826 + _EPS
            self.envelopes[ch] = ChannelEnvelope(med, mad)
            if ch == "crimp_force":
                shapes = np.array([_shape_features(row) for row in mat])
                s_med = np.nanmedian(shapes, axis=0)
                s_mad = np.nanmedian(np.abs(shapes - s_med), axis=0) * 1.4826 + _EPS
                self.shape_ref[ch] = (s_med, s_mad)
        # scale so a typical training unit scores ~0.1–0.3
        train_scores = self._raw_scores(train)
        p95 = float(np.nanpercentile(list(train_scores.values()), 95)) if train_scores else 1.0
        self._score_scale = max(p95, _EPS)
        return self

    def _raw_scores(self, sensors: pd.DataFrame) -> dict[str, float]:
        scores: dict[str, float] = {}
        assert self.channels is not None
        per_channel: dict[str, pd.DataFrame] = {
            ch: _pivot(sensors, ch) for ch in self.channels if ch in self.envelopes
        }
        unit_ids: set[str] = set()
        for mat in per_channel.values():
            unit_ids.update(mat.index)
        for uid in unit_ids:
            worst = 0.0
            for ch, mat in per_channel.items():
                if uid not in mat.index:
                    continue
                wave = mat.loc[uid].to_numpy(dtype=float)
                env = self.envelopes[ch]
                n = min(len(wave), len(env.median))
                z = np.abs(wave[:n] - env.median[:n]) / env.mad[:n]
                z = np.clip(z, 0, _Z_CAP)
                excursion = float(np.nanpercentile(z, 98)) if not np.all(np.isnan(z)) else 0.0
                score = excursion
                if ch in self.shape_ref:
                    s_med, s_mad = self.shape_ref[ch]
                    sz = np.abs(_shape_features(wave) - s_med) / s_mad
                    shape_dev = float(np.nanmax(np.clip(sz, 0, _Z_CAP)))
                    score = 0.6 * excursion + 0.4 * shape_dev
                worst = max(worst, score)
            scores[str(uid)] = worst
        return scores

    def anomaly_scores(self, sensors: pd.DataFrame) -> pd.Series:
        """Score per unit in [0, ~1+] (1.0 ≈ training 95th percentile)."""
        raw = self._raw_scores(sensors)
        return pd.Series(
            {u: min(2.0, s / self._score_scale) / 2.0 for u, s in raw.items()},
            name="ts_anomaly",
        )
