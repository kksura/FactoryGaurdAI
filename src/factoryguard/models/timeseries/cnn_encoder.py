"""1D-CNN time-series embedding model (spec §8.2, Phase 4).

Windowed, mask-aware, train-statistics-normalized waveforms → a shared
convolutional encoder with three outputs:

- ``embed``: fixed-size unit embeddings (fusion + retrieval + OOD input);
- ``predict_proba``: supervised defect probability head;
- ``anomaly_score``: reconstruction-error score (decoder trained on the
  training period without labels — usable in ``anomaly-only`` mode).

Sensor dropout (NaN gaps) is represented explicitly: each channel carries a
companion binary observed-mask channel and NaNs are zero-filled *after*
normalization — the model always sees "missing", never a fake reading.

Optional SSL pretraining (config flag, ADR-0021): masked-segment
reconstruction on unlabeled training waveforms before the supervised head
is fitted, evaluated against the supervised-only encoder in the report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

_EPS = 1e-6


@dataclass
class TsTensor:
    """Stacked per-unit waveforms: values + observed masks, fixed length."""

    unit_ids: list[str]
    values: np.ndarray  # (n, C, L) float32, NaN where unobserved
    channels: list[str]

    @property
    def index(self) -> pd.Index:
        return pd.Index(self.unit_ids, name="unit_id")


def build_ts_tensor(
    sensors: pd.DataFrame, length: int = 128, channels: list[str] | None = None
) -> TsTensor:
    """Long-format sensor table → (n, C, L) tensor. Channels with a
    different native length are linearly interpolated onto ``length``
    points (NaN gaps survive interpolation as NaN)."""
    channels = channels or sorted(sensors["channel"].unique())
    mats: list[np.ndarray] = []
    ids: pd.Index | None = None
    for ch in channels:
        pivot = sensors[sensors.channel == ch].pivot_table(
            index="unit_id", columns="t", values="value", dropna=False
        )
        if ids is None:
            ids = pivot.index
        else:
            pivot = pivot.reindex(ids)
        arr = pivot.to_numpy(dtype=np.float32)
        if arr.shape[1] != length:
            arr = _resample(arr, length)
        mats.append(arr)
    assert ids is not None, "sensors frame is empty"
    values = np.stack(mats, axis=1)  # (n, C, L)
    return TsTensor(unit_ids=[str(u) for u in ids], values=values, channels=channels)


def _resample(arr: np.ndarray, length: int) -> np.ndarray:
    """Linear interpolation onto a fixed grid; NaN runs stay NaN."""
    n, src = arr.shape
    x_new = np.linspace(0.0, 1.0, length)
    x_old = np.linspace(0.0, 1.0, src)
    out = np.empty((n, length), dtype=np.float32)
    for i in range(n):
        row = arr[i]
        ok = np.isfinite(row)
        if ok.sum() < 2:
            out[i] = np.nan
            continue
        out[i] = np.interp(x_new, x_old[ok], row[ok]).astype(np.float32)
        # re-punch NaN gaps: grid points nearest to an unobserved source point
        nearest = np.clip(np.round(x_new * (src - 1)).astype(int), 0, src - 1)
        out[i, ~ok[nearest]] = np.nan
    return out


class TsCnnEncoder:
    """Shared 1D-CNN encoder + supervised head + reconstruction decoder."""

    name = "ts_cnn"

    def __init__(
        self,
        length: int = 128,
        embed_dim: int = 64,
        epochs: int = 15,
        ssl_pretrain: bool = False,
        ssl_epochs: int = 10,
        batch_size: int = 256,
        lr: float = 1e-3,
        seed: int = 0,
        device: str | None = None,
    ) -> None:
        import torch

        self.length = length
        self.embed_dim = embed_dim
        self.epochs = epochs
        self.ssl_pretrain = ssl_pretrain
        self.ssl_epochs = ssl_epochs
        self.batch_size = batch_size
        self.lr = lr
        self.seed = seed
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model: Any = None
        self._mean: np.ndarray | None = None  # (C, 1) train stats
        self._std: np.ndarray | None = None
        self._recon_scale: float = 1.0
        self.channels: list[str] = []

    # ------------------------------------------------------------------ setup

    def _build(self, n_channels: int) -> None:
        import torch
        from torch import nn

        torch.manual_seed(self.seed)

        class _Net(nn.Module):
            def __init__(self, c_in: int, embed_dim: int, length: int) -> None:
                super().__init__()
                self.encoder = nn.Sequential(
                    nn.Conv1d(c_in, 32, kernel_size=7, padding=3),
                    nn.GroupNorm(4, 32),
                    nn.ReLU(),
                    nn.MaxPool1d(2),
                    nn.Conv1d(32, 64, kernel_size=5, padding=2),
                    nn.GroupNorm(8, 64),
                    nn.ReLU(),
                    nn.MaxPool1d(2),
                    nn.Conv1d(64, 64, kernel_size=3, padding=1),
                    nn.GroupNorm(8, 64),
                    nn.ReLU(),
                    nn.AdaptiveAvgPool1d(1),
                    nn.Flatten(),
                    nn.Linear(64, embed_dim),
                )
                self.cls_head = nn.Linear(embed_dim, 1)
                self.decoder = nn.Sequential(
                    nn.Linear(embed_dim, 128),
                    nn.ReLU(),
                    nn.Linear(128, (c_in // 2) * length),
                )
                self.c_out = c_in // 2
                self.length = length

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                return self.encoder(x)

            def reconstruct(self, z: torch.Tensor) -> torch.Tensor:
                return self.decoder(z).view(-1, self.c_out, self.length)

        self._model = _Net(n_channels, self.embed_dim, self.length).to(self.device)

    # Torch modules built as local classes aren't picklable; artifacts
    # persist the weights (state_dict) and rebuild the architecture on load.
    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        model = state.pop("_model")
        state["_model_state"] = (
            None if model is None else {k: v.cpu() for k, v in model.state_dict().items()}
        )
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        model_state = state.pop("_model_state", None)
        self.__dict__.update(state)
        self._model = None
        if model_state is not None:
            assert self._mean is not None
            self._build(2 * self._mean.shape[0])
            self._model.load_state_dict(model_state)
            self._model.eval()

    def _normalize(self, values: np.ndarray) -> np.ndarray:
        """(n, C, L) → (n, 2C, L): normalized zero-filled values + masks."""
        assert self._mean is not None and self._std is not None
        observed = np.isfinite(values)
        z = (values - self._mean) / self._std
        z = np.where(observed, z, 0.0).astype(np.float32)
        return np.concatenate([z, observed.astype(np.float32)], axis=1)

    # -------------------------------------------------------------------- fit

    def fit(
        self,
        tensor: TsTensor,
        y: np.ndarray | None,
        sample_index: np.ndarray | None = None,
        val_index: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> TsCnnEncoder:
        """Train on the given units (all rows unless ``sample_index`` given).

        ``y`` are binary defect labels for the supervised head; pass ``None``
        to train only the unsupervised decoder (anomaly-only deployments).
        Normalization statistics come from these training units only.

        When ``val_index``/``y_val`` are given, the supervised head keeps the
        epoch with the best validation ROC-AUC instead of the last one — a
        small CNN memorizes a few thousand waveforms long before the epoch
        budget runs out, and under temporal drift the memorized fit can score
        *below* chance on later periods (observed on the small profile).
        """
        import torch
        from torch import nn

        vals = tensor.values if sample_index is None else tensor.values[sample_index]
        y_arr = None if y is None else np.asarray(y, dtype=np.float32)
        self.channels = tensor.channels

        self._mean = np.nanmean(vals, axis=(0, 2), keepdims=True)[0]
        self._std = np.nanstd(vals, axis=(0, 2), keepdims=True)[0] + _EPS
        x = self._normalize(vals)
        self._build(x.shape[1])
        model = self._model
        assert model is not None

        xt = torch.from_numpy(x)
        target = torch.from_numpy(
            np.where(np.isfinite(vals), (vals - self._mean) / self._std, 0.0).astype(np.float32)
        )
        obs = torch.from_numpy(np.isfinite(vals).astype(np.float32))
        gen = torch.Generator().manual_seed(self.seed)

        if self.ssl_pretrain:
            self._run_recon_epochs(xt, target, obs, self.ssl_epochs, masked=True, generator=gen)
            log.info("%s: SSL masked-reconstruction pretraining done", self.name)

        if y_arr is not None:
            pos = max(1.0, float((~y_arr.astype(bool)).sum()) / max(1.0, float(y_arr.sum())))
            bce = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(pos, device=self.device))
            opt = torch.optim.Adam(model.parameters(), lr=self.lr)
            yt = torch.from_numpy(y_arr)
            x_val = None
            if val_index is not None and y_val is not None and np.asarray(y_val).any():
                x_val = torch.from_numpy(self._normalize(tensor.values[val_index]))
            best_auc, best_state = -1.0, None
            for _ in range(self.epochs):
                for idx in torch.randperm(len(xt), generator=gen).split(self.batch_size):
                    xb = xt[idx].to(self.device)
                    logits = model.cls_head(model(xb)).squeeze(-1)
                    loss = bce(logits, yt[idx].to(self.device))
                    opt.zero_grad()
                    loss.backward()
                    opt.step()
                if x_val is not None:
                    from sklearn.metrics import roc_auc_score

                    with torch.no_grad():
                        val_logits = model.cls_head(model(x_val.to(self.device))).squeeze(-1)
                    auc = float(roc_auc_score(np.asarray(y_val), val_logits.cpu().numpy()))
                    if auc > best_auc:
                        best_auc = auc
                        best_state = {k: v.clone() for k, v in model.state_dict().items()}
            if best_state is not None:
                model.load_state_dict(best_state)
                log.info("%s: kept best-val-AUC epoch (val ROC-AUC %.3f)", self.name, best_auc)

        # Decoder always trains label-free (anomaly path, ADR-0019). Encoder
        # is frozen here when a supervised head was trained, so the anomaly
        # score stays a pure reconstruction signal on top of the same
        # representation rather than un-learning the classification features.
        self._run_recon_epochs(
            xt,
            target,
            obs,
            max(3, self.ssl_epochs // 2),
            masked=False,
            generator=gen,
            decoder_only=y_arr is not None,
        )
        err = self._recon_errors(tensor.values if sample_index is None else vals)
        self._recon_scale = max(float(np.percentile(err, 95)), _EPS)
        return self

    def _run_recon_epochs(
        self,
        xt: Any,
        target: Any,
        obs: Any,
        epochs: int,
        masked: bool,
        generator: Any,
        decoder_only: bool = False,
    ) -> None:
        import torch

        model = self._model
        assert model is not None
        params = list(model.decoder.parameters()) if decoder_only else list(model.parameters())
        opt = torch.optim.Adam(params, lr=self.lr)
        c = target.shape[1]
        for _ in range(epochs):
            for idx in torch.randperm(len(xt), generator=generator).split(self.batch_size):
                xb = xt[idx].clone().to(self.device)
                tb = target[idx].to(self.device)
                ob = obs[idx].to(self.device)
                loss_mask = ob
                if masked:
                    # hide two contiguous 15% segments per sample; loss only
                    # on hidden-but-observed points (masked reconstruction)
                    seg = max(1, int(0.15 * self.length))
                    hide = torch.zeros_like(ob, dtype=torch.bool)
                    for _s in range(2):
                        starts = torch.randint(
                            0, self.length - seg, (len(xb),), generator=generator
                        ).to(self.device)
                        ar = torch.arange(self.length, device=self.device)
                        span = (ar >= starts[:, None]) & (ar < (starts + seg)[:, None])
                        hide |= span[:, None, :].expand(-1, c, -1)
                    xb[:, :c][hide] = 0.0
                    xb[:, c:][hide] = 0.0  # hidden points are "unobserved" to the model
                    loss_mask = ob * hide.float()
                z = model(xb)
                rec = model.reconstruct(z)
                denom = loss_mask.sum().clamp(min=1.0)
                loss = (((rec - tb) ** 2) * loss_mask).sum() / denom
                opt.zero_grad()
                loss.backward()
                opt.step()

    # -------------------------------------------------------------- inference

    def _forward_batched(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """→ (embeddings, logits, per-unit reconstruction MSE)."""
        import torch

        model = self._model
        assert model is not None, "fit() first"
        assert self._mean is not None and self._std is not None
        x = self._normalize(values)
        target = np.where(np.isfinite(values), (values - self._mean) / self._std, 0.0).astype(
            np.float32
        )
        obs = np.isfinite(values).astype(np.float32)
        embs, logits, errs = [], [], []
        with torch.no_grad():
            for start in range(0, len(x), 512):
                xb = torch.from_numpy(x[start : start + 512]).to(self.device)
                tb = torch.from_numpy(target[start : start + 512]).to(self.device)
                ob = torch.from_numpy(obs[start : start + 512]).to(self.device)
                z = model(xb)
                lg = model.cls_head(z).squeeze(-1)
                rec = model.reconstruct(z)
                per_unit = (((rec - tb) ** 2) * ob).sum(dim=(1, 2)) / ob.sum(dim=(1, 2)).clamp(
                    min=1.0
                )
                embs.append(z.cpu().numpy())
                logits.append(lg.cpu().numpy())
                errs.append(per_unit.cpu().numpy())
        return (
            np.concatenate(embs) if embs else np.zeros((0, self.embed_dim), dtype=np.float32),
            np.concatenate(logits) if logits else np.zeros(0, dtype=np.float32),
            np.concatenate(errs) if errs else np.zeros(0, dtype=np.float32),
        )

    def _recon_errors(self, values: np.ndarray) -> np.ndarray:
        return self._forward_batched(values)[2]

    def embed(self, tensor: TsTensor) -> np.ndarray:
        return self._forward_batched(tensor.values)[0]

    def predict_proba(self, tensor: TsTensor) -> np.ndarray:
        """(n, 2) [P(ok), P(defect)] — uncalibrated until Phase 4 calibration."""
        logits = self._forward_batched(tensor.values)[1]
        p = 1.0 / (1.0 + np.exp(-logits))
        return np.stack([1.0 - p, p], axis=1)

    def anomaly_score(self, tensor: TsTensor) -> np.ndarray:
        """[0, 1] reconstruction-error score (1 ≈ 2× the train p95).
        Rank-evaluated only — never a calibrated probability (ADR-0019)."""
        err = self._recon_errors(tensor.values)
        return np.clip(err / (2.0 * self._recon_scale), 0.0, 1.0)
