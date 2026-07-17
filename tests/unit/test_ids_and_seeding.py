from factoryguard.utilities.ids import (
    is_valid_correlation_id,
    new_correlation_id,
    new_prediction_id,
)
from factoryguard.utilities.seeding import derive_seed, rng_for


def test_prediction_ids_unique_and_prefixed() -> None:
    ids = {new_prediction_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(i.startswith("prd-") for i in ids)


def test_correlation_id_roundtrip() -> None:
    cid = new_correlation_id()
    assert is_valid_correlation_id(cid)
    assert not is_valid_correlation_id("cor-<script>")
    assert not is_valid_correlation_id("attack\nvalue")
    assert not is_valid_correlation_id("cor-" + "z" * 32)


def test_derive_seed_stable_and_scoped() -> None:
    assert derive_seed(42, "images", 7) == derive_seed(42, "images", 7)
    assert derive_seed(42, "images", 7) != derive_seed(42, "images", 8)
    assert derive_seed(42, "images") != derive_seed(42, "timeseries")
    assert derive_seed(41, "images") != derive_seed(42, "images")


def test_rng_streams_independent() -> None:
    a1 = rng_for(42, "a").normal(size=5)
    b1 = rng_for(42, "b").normal(size=5)
    a2 = rng_for(42, "a").normal(size=5)
    assert (a1 == a2).all()
    assert not (a1 == b1).all()
