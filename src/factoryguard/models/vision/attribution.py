"""Attention attribution for the frozen DINOv2 encoder (spec §8.3/§10).

Produces per-image patch-level heatmaps from the ViT's self-attention:

- ``last``: CLS-token attention of the final block, averaged over heads —
  cheap, sharp, the default for reports;
- ``rollout``: attention rollout (Abnar & Zuidema 2020) across all blocks
  with residual correction — smoother, whole-network attribution.

The maps are *model attribution*, not causation (spec §10 wording rules),
and are validated in tests against the known synthetic defect geometry:
the generator draws the harness along the horizontal center band, so
attention mass must concentrate there rather than in the empty border.

Implementation note: the DINOv2 hub attention modules don't expose their
attention weights, so a forward hook captures each block's qkv projection
and the attention matrix is recomputed here (softmax(q·kᵀ/√d)).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from factoryguard.models.vision.dinov2 import (
    _IMAGENET_MEAN,
    _IMAGENET_STD,
    _INPUT_SIZE,
    Dinov2Encoder,
)

PATCH = 14
GRID = _INPUT_SIZE // PATCH  # 8×8 patches at the 112-px input size


def _preprocess(paths: list[Path]) -> np.ndarray:
    batch = []
    for p in paths:
        img = Image.open(p).convert("L").resize((_INPUT_SIZE, _INPUT_SIZE))
        arr = np.asarray(img, dtype=np.float32) / 255.0
        rgb = np.repeat(arr[..., None], 3, axis=-1)
        rgb = (rgb - _IMAGENET_MEAN) / _IMAGENET_STD
        batch.append(rgb.transpose(2, 0, 1))
    return np.stack(batch)


def _attention_from_qkv(qkv: Any, num_heads: int) -> Any:
    """qkv linear output (B, N, 3·D) → per-head attention (B, H, N, N)."""
    import torch

    b, n, three_d = qkv.shape
    d = three_d // 3
    head_dim = d // num_heads
    q, k, _ = qkv.reshape(b, n, 3, num_heads, head_dim).permute(2, 0, 3, 1, 4).unbind(0)
    return torch.softmax(q @ k.transpose(-2, -1) / head_dim**0.5, dim=-1)


def attention_maps(
    encoder: Dinov2Encoder,
    paths: list[Path],
    method: str = "last",
    batch_size: int = 32,
) -> np.ndarray:
    """CLS→patch attention heatmaps, (n, GRID, GRID), each summing to 1."""
    import torch

    if method not in ("last", "rollout"):
        raise ValueError("method must be 'last' or 'rollout'")
    encoder._load()
    model: Any = encoder._model
    blocks = model.blocks if method == "rollout" else [model.blocks[-1]]
    num_heads = int(blocks[-1].attn.num_heads)

    captured: list[Any] = []
    hooks = [
        blk.attn.qkv.register_forward_hook(lambda _m, _i, out: captured.append(out))
        for blk in blocks
    ]
    out_maps: list[np.ndarray] = []
    try:
        for start in range(0, len(paths), batch_size):
            captured.clear()
            x = torch.from_numpy(_preprocess(paths[start : start + batch_size])).to(encoder.device)
            with torch.no_grad():
                model(x)
            attns = [_attention_from_qkv(q, num_heads).mean(dim=1) for q in captured]
            if method == "last":
                cls_attn = attns[-1][:, 0, 1:]
            else:
                n = attns[0].shape[-1]
                eye = torch.eye(n, device=attns[0].device)
                rolled = eye.expand(attns[0].shape[0], n, n)
                for a in attns:
                    a = (a + eye) / 2.0  # residual correction
                    a = a / a.sum(dim=-1, keepdim=True)
                    rolled = a @ rolled
                cls_attn = rolled[:, 0, 1:]
            cls_attn = cls_attn / cls_attn.sum(dim=-1, keepdim=True)
            out_maps.append(cls_attn.reshape(-1, GRID, GRID).cpu().numpy())
    finally:
        for h in hooks:
            h.remove()
    return np.concatenate(out_maps) if out_maps else np.zeros((0, GRID, GRID), dtype=np.float32)


def center_band_mass(maps: np.ndarray, band_rows: tuple[int, int] = (2, 6)) -> np.ndarray:
    """Fraction of attention mass in the horizontal center band (rows
    [band_rows[0], band_rows[1])) where the synthetic harness is drawn.
    A uniform map scores (band width / GRID); the geometry-validation test
    requires real maps to beat that baseline."""
    lo, hi = band_rows
    return maps[:, lo:hi, :].sum(axis=(1, 2))
