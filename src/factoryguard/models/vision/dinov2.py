"""Vision baseline (ADR-0018): frozen DINOv2-small encoder + trained head.

- Embeddings from the frozen ViT-S/14 backbone (384-d) feed classification,
  k-NN probing, retrieval, and the image-distance cold-start anomaly scorer.
- Weights come from torch.hub pinned to a ref; the download happens once at
  fit/embed time and the checkpoint SHA-256 is recorded for the registry.
- Everything runs on CPU or CUDA; grayscale inputs are channel-repeated and
  resized to a multiple of the 14-px patch size.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier

from factoryguard.security.checksums import IntegrityError, sha256_file

log = logging.getLogger(__name__)

HUB_REPO = "facebookresearch/dinov2"
HUB_MODEL = "dinov2_vits14"
_CHECKPOINT_FILENAME = "dinov2_vits14_pretrain.pth"
# Pinned checksum of the official pretrained checkpoint (ADR-0012/0018:
# pretrained weights are supply-chain artifacts and must be integrity
# verified, not merely trusted, before being used for inference).
# Recorded 2026-07-17 from the file downloaded via torch.hub from
# https://dl.fbaipublicfiles.com/dinov2/dinov2_vits14/dinov2_vits14_pretrain.pth
EXPECTED_CHECKPOINT_SHA256 = "b938bf1bc15cd2ec0feacfe3a1bb553fe8ea9ca46a7e1d8d00217f29aef60cd9"
_INPUT_SIZE = 112  # 8 × 14-px patches
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class Dinov2Encoder:
    """Lazy-loading frozen encoder; one instance per process."""

    def __init__(self, device: str | None = None, verify_checksum: bool = True) -> None:
        import torch

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.verify_checksum = verify_checksum
        self._model: object | None = None

    def _verify_checkpoint(self) -> None:
        import torch.hub

        checkpoint = Path(torch.hub.get_dir()) / "checkpoints" / _CHECKPOINT_FILENAME
        if not checkpoint.is_file():
            return  # not yet cached — torch.hub.load will fetch it, verify on next call
        actual = sha256_file(checkpoint)
        if actual != EXPECTED_CHECKPOINT_SHA256:
            raise IntegrityError(
                f"DINOv2 checkpoint checksum mismatch: {actual} != "
                f"{EXPECTED_CHECKPOINT_SHA256} (file: {checkpoint}). Refusing to "
                "load a pretrained weight file that doesn't match the pinned "
                "checksum — it may be corrupted or tampered with."
            )
        log.info("DINOv2 checkpoint checksum verified: %s", actual)

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch

        log.info("loading %s/%s on %s", HUB_REPO, HUB_MODEL, self.device)
        model = torch.hub.load(HUB_REPO, HUB_MODEL, trust_repo=True)
        if self.verify_checksum:
            self._verify_checkpoint()
        model.eval().to(self.device)
        self._model = model

    def embed_paths(self, paths: list[Path], batch_size: int = 64) -> np.ndarray:
        """Embed image files → (n, 384) float32."""
        import torch

        self._load()
        assert self._model is not None
        out: list[np.ndarray] = []
        for start in range(0, len(paths), batch_size):
            batch = []
            for p in paths[start : start + batch_size]:
                img = Image.open(p).convert("L").resize((_INPUT_SIZE, _INPUT_SIZE))
                arr = np.asarray(img, dtype=np.float32) / 255.0
                rgb = np.repeat(arr[..., None], 3, axis=-1)
                rgb = (rgb - _IMAGENET_MEAN) / _IMAGENET_STD
                batch.append(rgb.transpose(2, 0, 1))
            x = torch.from_numpy(np.stack(batch)).to(self.device)
            with torch.no_grad():
                emb = self._model(x)  # type: ignore[operator]
            out.append(emb.float().cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, 384), dtype=np.float32)


class Dinov2Classifier:
    """Frozen encoder + logistic head; optional k-NN probe mode."""

    name = "dinov2_head"

    def __init__(self, encoder: Dinov2Encoder, mode: str = "linear", seed: int = 0) -> None:
        if mode not in ("linear", "knn"):
            raise ValueError("mode must be linear or knn")
        self.encoder = encoder
        self.mode = mode
        self.head = (
            LogisticRegression(max_iter=3000, class_weight="balanced", random_state=seed)
            if mode == "linear"
            else KNeighborsClassifier(n_neighbors=5, weights="distance")
        )

    def fit_embeddings(self, emb: np.ndarray, y: np.ndarray) -> Dinov2Classifier:
        self.head.fit(emb, y)
        return self

    def predict_proba_embeddings(self, emb: np.ndarray) -> np.ndarray:
        return self.head.predict_proba(emb)

    @property
    def classes_(self) -> np.ndarray:
        return self.head.classes_


class ImageDistanceAnomaly:
    """Cold-start image anomaly (ADR-0019): distance to the k nearest
    *reference* embeddings (a golden set of training images, labels unused).
    """

    name = "image_distance"

    def __init__(self, k: int = 5) -> None:
        self.k = k
        self._ref: np.ndarray | None = None
        self._scale: float = 1.0

    def fit(self, reference_embeddings: np.ndarray) -> ImageDistanceAnomaly:
        self._ref = np.asarray(reference_embeddings, dtype=np.float32)
        d = self._knn_dist(self._ref, exclude_self=True)
        self._scale = float(np.percentile(d, 95)) or 1.0
        return self

    def _knn_dist(self, emb: np.ndarray, exclude_self: bool = False) -> np.ndarray:
        assert self._ref is not None
        # exact search — dataset scales make a vector DB unnecessary (ADR-0021)
        d2 = (
            np.sum(emb**2, axis=1, keepdims=True)
            - 2 * emb @ self._ref.T
            + np.sum(self._ref**2, axis=1)
        )
        d2 = np.maximum(d2, 0)
        k = self.k + (1 if exclude_self else 0)
        idx = np.argsort(d2, axis=1)[:, :k]
        dists = np.sqrt(np.take_along_axis(d2, idx, axis=1))
        if exclude_self:
            dists = dists[:, 1:]
        return dists.mean(axis=1)

    def anomaly_score(self, emb: np.ndarray) -> np.ndarray:
        """[0, 1] where 1 ≈ far outside the reference distribution."""
        d = self._knn_dist(np.asarray(emb, dtype=np.float32))
        return np.clip(d / (2 * self._scale), 0.0, 1.0)
