"""DINOv2 attention attribution validated against the known synthetic
defect geometry (spec §8.3): the generator draws the harness along the
horizontal center band, so real attention maps must put more mass there
than a uniform map would.

Skipped when the pinned DINOv2 checkpoint isn't in the torch.hub cache —
these tests must not trigger a network download.
"""

from pathlib import Path

import numpy as np
import pytest

from factoryguard.data.generate import generate_dataset


def _checkpoint_cached() -> bool:
    try:
        import torch.hub

        from factoryguard.models.vision.dinov2 import _CHECKPOINT_FILENAME

        return (Path(torch.hub.get_dir()) / "checkpoints" / _CHECKPOINT_FILENAME).is_file()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _checkpoint_cached(), reason="DINOv2 checkpoint not cached; no network in tests"
)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate_dataset("tiny", data_root=tmp_path_factory.mktemp("attr"))


def test_attention_concentrates_on_harness_band(dataset: Path) -> None:
    import pandas as pd

    from factoryguard.models.vision.attribution import attention_maps, center_band_mass
    from factoryguard.models.vision.dinov2 import Dinov2Encoder

    meta = pd.read_parquet(dataset / "tables" / "image_metadata.parquet")
    if meta.empty:
        pytest.skip("tiny profile generated no images")
    sample = meta.head(16)
    paths = [dataset / p for p in sample["image_path"]]
    encoder = Dinov2Encoder()

    for method in ("last", "rollout"):
        maps = attention_maps(encoder, paths, method=method)
        assert maps.shape == (len(paths), 8, 8)
        np.testing.assert_allclose(maps.sum(axis=(1, 2)), 1.0, atol=1e-4)
        band = center_band_mass(maps)
        # uniform baseline: 4 of 8 rows = 0.5 of the mass
        assert band.mean() > 0.5, (
            f"{method}: attention does not concentrate on the harness geometry "
            f"(band mass {band.mean():.2f} ≤ uniform 0.50)"
        )
