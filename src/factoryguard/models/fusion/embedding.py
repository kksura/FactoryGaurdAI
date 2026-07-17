"""Embedding-level fusion (ADR-0006, challenger to late fusion).

Per-modality embeddings are standardized with train statistics, projected
to a common width, and combined by a gate conditioned on the availability
mask. A missing modality contributes a *learned* absent embedding — never
zeros — and its gate input says so. Trained with modality dropout so the
gate actually learns to reweight around missingness.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from factoryguard.models.fusion.inputs import FusionInput

log = logging.getLogger(__name__)
_EPS = 1e-6


class EmbeddingFusion:
    name = "embedding_fusion"

    def __init__(
        self,
        proj_dim: int = 32,
        epochs: int = 60,
        lr: float = 3e-3,
        dropout_rate: float = 0.3,
        batch_size: int = 512,
        seed: int = 0,
        device: str | None = None,
    ) -> None:
        import torch

        self.proj_dim = proj_dim
        self.epochs = epochs
        self.lr = lr
        self.dropout_rate = dropout_rate
        self.batch_size = batch_size
        self.seed = seed
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.modalities: list[str] = []
        self._model: Any = None
        self._stats: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    # See TsCnnEncoder: local torch classes aren't picklable — persist
    # weights and rebuild the architecture on load.
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
            self._build([self._stats[m][0].shape[0] for m in self.modalities])
            self._model.load_state_dict(model_state)
            self._model.eval()

    def _standardize(self, inputs: FusionInput) -> tuple[list[np.ndarray], np.ndarray]:
        mask = inputs.embedding_mask(self.modalities)
        mats = []
        for i, m in enumerate(self.modalities):
            mean, std = self._stats[m]
            z = (inputs.embeddings[m] - mean) / std
            z = np.where(mask[:, i : i + 1], z, 0.0).astype(np.float32)  # placeholder;
            # the model swaps zeroed rows for its learned absent embedding
            mats.append(z)
        return mats, mask

    def _build(self, dims: list[int]) -> None:
        import torch
        from torch import nn

        torch.manual_seed(self.seed)
        n_mod = len(dims)
        proj_dim = self.proj_dim

        class _Net(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.projs = nn.ModuleList(nn.Linear(d, proj_dim) for d in dims)
                self.absent = nn.Parameter(torch.zeros(n_mod, proj_dim))
                nn.init.normal_(self.absent, std=0.02)
                self.gate = nn.Linear(n_mod, n_mod)
                self.head = nn.Sequential(nn.Linear(proj_dim, 32), nn.ReLU(), nn.Linear(32, 1))

            def fuse(self, xs: list[torch.Tensor], mask: torch.Tensor) -> torch.Tensor:
                z = torch.stack(
                    [proj(x) for proj, x in zip(self.projs, xs, strict=True)], dim=1
                )  # (B, M, P)
                m = mask.unsqueeze(-1)  # (B, M, 1)
                z = m * z + (1.0 - m) * self.absent.unsqueeze(0)
                w = torch.sigmoid(self.gate(mask))  # gate conditioned on availability
                w = w / (w.sum(dim=1, keepdim=True) + 1e-6)
                return (w.unsqueeze(-1) * z).sum(dim=1)  # (B, P)

            def forward(self, xs: list[torch.Tensor], mask: torch.Tensor) -> torch.Tensor:
                return self.head(self.fuse(xs, mask)).squeeze(-1)

        self._model = _Net().to(self.device)

    def fit(self, inputs: FusionInput, y: np.ndarray) -> EmbeddingFusion:
        import torch
        from torch import nn

        self.modalities = sorted(inputs.embeddings)
        for m in self.modalities:
            emb = inputs.embeddings[m]
            present = np.isfinite(emb).all(axis=1)
            ref = emb[present] if present.any() else np.zeros((1, emb.shape[1]))
            self._stats[m] = (ref.mean(axis=0), ref.std(axis=0) + _EPS)

        mats, mask = self._standardize(inputs)
        self._build([m.shape[1] for m in mats])
        model = self._model
        y_arr = np.asarray(y, dtype=np.float32)
        pos = max(1.0, float((~y_arr.astype(bool)).sum()) / max(1.0, float(y_arr.sum())))
        bce = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(pos, device=self.device))
        opt = torch.optim.Adam(model.parameters(), lr=self.lr)
        gen = torch.Generator().manual_seed(self.seed)

        xt = [torch.from_numpy(m) for m in mats]
        mt = torch.from_numpy(mask.astype(np.float32))
        yt = torch.from_numpy(y_arr)
        for _ in range(self.epochs):
            for idx in torch.randperm(len(yt), generator=gen).split(self.batch_size):
                mb = mt[idx].clone()
                # modality dropout: hide present modalities at random, but
                # never leave a row with no modality at all
                drop = torch.rand(mb.shape, generator=gen) < self.dropout_rate
                cand = mb * (~drop).float()
                mb = torch.where(cand.sum(dim=1, keepdim=True) > 0, cand, mb)
                logits = model([x[idx].to(self.device) for x in xt], mb.to(self.device))
                loss = bce(logits, yt[idx].to(self.device))
                opt.zero_grad()
                loss.backward()
                opt.step()
        return self

    def predict_proba(self, inputs: FusionInput) -> np.ndarray:
        logits = self._forward(inputs, fused=False)
        p = 1.0 / (1.0 + np.exp(-logits))
        return np.stack([1.0 - p, p], axis=1)

    def embed(self, inputs: FusionInput) -> np.ndarray:
        """Fused representation (n, proj_dim) — OOD + retrieval input."""
        return self._forward(inputs, fused=True)

    def _forward(self, inputs: FusionInput, fused: bool) -> np.ndarray:
        import torch

        model = self._model
        assert model is not None, "fit() first"
        mats, mask = self._standardize(inputs)
        out: list[np.ndarray] = []
        with torch.no_grad():
            for start in range(0, len(mask), 2048):
                xs = [torch.from_numpy(m[start : start + 2048]).to(self.device) for m in mats]
                mb = torch.from_numpy(mask[start : start + 2048].astype(np.float32)).to(self.device)
                res = model.fuse(xs, mb) if fused else model(xs, mb)
                out.append(res.cpu().numpy())
        if not out:
            return np.zeros((0, self.proj_dim) if fused else (0,), dtype=np.float32)
        return np.concatenate(out)

    def gate_weights(self, inputs: FusionInput) -> np.ndarray:
        """(n, M) normalized gate weights — fusion attribution for reports."""
        import torch

        model = self._model
        assert model is not None, "fit() first"
        _, mask = self._standardize(inputs)
        with torch.no_grad():
            w = torch.sigmoid(model.gate(torch.from_numpy(mask.astype(np.float32)).to(self.device)))
            w = w / (w.sum(dim=1, keepdim=True) + 1e-6)
        return np.asarray(w.cpu().numpy())
