"""Image-quality scorer must actually separate camera-degraded images from
healthy ones (regression test for the mis-calibrated threshold found during
Phase 3 review: an untested guessed threshold detected 0% of degraded
images)."""

from pathlib import Path

import pandas as pd
import pytest

from factoryguard.data.generate import generate_dataset
from factoryguard.models.vision.quality import assess_batch


@pytest.fixture(scope="module")
def small_dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate_dataset("small", data_root=tmp_path_factory.mktemp("quality"))


def test_blur_threshold_separates_degraded_images(small_dataset: Path) -> None:
    meta = pd.read_parquet(small_dataset / "tables" / "image_metadata.parquet")
    degraded = meta[meta.camera_degraded]
    if len(degraded) < 5:
        pytest.skip("not enough camera-degraded images in this generated dataset")
    scores = assess_batch([small_dataset / p for p in meta["image_path"]])
    meta = meta.assign(flagged=[s.is_degraded for s in scores])

    detect_rate = meta.loc[meta.camera_degraded, "flagged"].mean()
    false_flag_rate = meta.loc[~meta.camera_degraded, "flagged"].mean()

    assert detect_rate > 0.7, f"quality scorer detects too few degraded images ({detect_rate:.2%})"
    assert false_flag_rate < 0.3, (
        f"quality scorer over-flags healthy images ({false_flag_rate:.2%})"
    )
