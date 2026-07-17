"""Image-quality assessment — deliberately separate from defect detection.

Scenario C (camera misalignment) requires the system to recognize that an
image is blurry/degraded *without* concluding the product is defective.
Conflating "the camera is bad" with "the crimp is bad" (as a single
embedding-distance anomaly score would) is exactly the failure this module
exists to prevent: a quality-degraded image should raise a data-quality
flag and reduce confidence, not raise the defect probability.

Pure PIL/numpy — no extra dependency, deterministic, fast.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

# Calibrated empirically 2026-07-17 against data/small (651 images, 31
# camera-degraded via the latent camera_misalignment window): sharp renders
# score mean=399 (min=96, p25=267) on the Laplacian variance below; the
# deliberately blurred camera-misalignment images score mean=148 (p90=213,
# max=255). A threshold of 225 gives ~90% detection at ~15% false-flag rate
# on that data (see docs/test-evidence.md). An earlier guessed threshold of
# 12 was off by more than an order of magnitude and detected 0% of degraded
# images — recalibrate the same way if the generator's rendering changes.
_BLUR_VARIANCE_LOW = 225.0
# exposure_spread showed no separation for this generator's blur-only
# degradation (mean 52.5 degraded vs 53.4 normal) — kept as a generic
# secondary signal for degradation modes (e.g. real lighting/exposure
# faults) this synthetic generator doesn't produce, set conservatively so
# it does not contribute false flags on this dataset.
_EXPOSURE_SPREAD_LOW = 10.0


@dataclass
class QualityScore:
    blur_variance: float  # Laplacian variance; low = blurry
    exposure_spread: float  # intensity std-dev; low = flat/washed-out
    is_degraded: bool
    reasons: list[str]


def _laplacian_variance(arr: np.ndarray) -> float:
    # 3x3 Laplacian kernel via PIL for a dependency-free sharpness proxy.
    img = Image.fromarray(arr.astype(np.uint8), mode="L")
    lap = img.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1))
    return float(np.asarray(lap, dtype=np.float32).var())


def assess(path: Path) -> QualityScore:
    img = Image.open(path).convert("L")
    arr = np.asarray(img, dtype=np.float32)
    blur_var = _laplacian_variance(arr)
    exposure_spread = float(arr.std())
    reasons = []
    if blur_var < _BLUR_VARIANCE_LOW:
        reasons.append("low_sharpness")
    if exposure_spread < _EXPOSURE_SPREAD_LOW:
        reasons.append("low_contrast")
    return QualityScore(
        blur_variance=blur_var,
        exposure_spread=exposure_spread,
        is_degraded=bool(reasons),
        reasons=reasons,
    )


def assess_batch(paths: list[Path]) -> list[QualityScore]:
    return [assess(p) for p in paths]
