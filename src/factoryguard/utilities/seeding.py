"""Deterministic seeding for reproducible data generation and training.

Every stochastic component takes an explicit ``numpy.random.Generator``;
module-level global RNG state is never used. ``derive_seed`` produces
stable per-component child seeds so adding a component never shifts the
random stream of another.
"""

from __future__ import annotations

import hashlib

import numpy as np

MAX_SEED = 2**32 - 1


def derive_seed(root_seed: int, *scope: str | int) -> int:
    """Derive a stable child seed from a root seed and a scope path.

    ``derive_seed(42, "images", plant_id)`` is stable across runs and
    independent of call order.
    """
    material = ":".join([str(root_seed), *map(str, scope)]).encode()
    digest = hashlib.sha256(material).digest()
    return int.from_bytes(digest[:4], "big") % (MAX_SEED + 1)


def rng_for(root_seed: int, *scope: str | int) -> np.random.Generator:
    """A dedicated Generator for one component/scope."""
    return np.random.default_rng(derive_seed(root_seed, *scope))


def seed_torch(seed: int) -> None:
    """Seed torch (CPU and CUDA) if torch is installed; no-op otherwise."""
    try:
        import torch
    except ImportError:
        return
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
