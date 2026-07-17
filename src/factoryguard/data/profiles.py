"""Dataset profile configuration (tiny/small/medium/large).

Profiles are YAML files under ``configs/data/``; this module parses and
validates them into typed objects. The profile config hash goes into the
dataset manifest so any config change produces a distinguishable dataset.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

PROFILE_NAMES = ("tiny", "small", "medium", "large")


class DateRange(BaseModel):
    start: date
    end: date

    @field_validator("end")
    @classmethod
    def _ordered(cls, v: date, info) -> date:  # type: ignore[no-untyped-def]
        if "start" in info.data and v <= info.data["start"]:
            raise ValueError("date_range.end must be after start")
        return v

    @property
    def days(self) -> int:
        return (self.end - self.start).days


class WorldConfig(BaseModel):
    plants: int = Field(ge=1)
    lines_per_plant: int = Field(ge=1)
    crimp_machines_per_line: int = Field(ge=1)
    operators_per_plant: int = Field(ge=3)
    suppliers: int = Field(ge=2)
    product_families: int = Field(ge=1)
    products_per_family: int = Field(ge=1)
    material_lots_per_component: int = Field(ge=2)


class ProductionConfig(BaseModel):
    units: int = Field(ge=50)
    units_per_work_order: int = Field(ge=5)
    target_defect_rate: float = Field(gt=0, lt=0.5)


class TimeseriesConfig(BaseModel):
    crimp_force_points: int = Field(ge=16)
    aux_points: int = Field(ge=8)
    aux_channels: list[str]
    sensor_dropout_rate: float = Field(ge=0, le=0.2)


class ImagesConfig(BaseModel):
    per_unit_probability: float = Field(ge=0, le=1)
    size: int = Field(ge=64, le=512)


class LabelsConfig(BaseModel):
    label_delay_days: int = Field(ge=0)
    label_noise_rate: float = Field(ge=0, le=0.1)


class MechanismConfig(BaseModel):
    """Free-form per-mechanism parameters; ``enabled`` is common to all."""

    model_config = {"extra": "allow"}
    enabled: bool = True

    def param(self, name: str, default: float) -> float:
        value = getattr(self, name, default)
        return float(value)


class Profile(BaseModel):
    profile: str
    seed: int = Field(ge=0)
    date_range: DateRange
    world: WorldConfig
    production: ProductionConfig
    timeseries: TimeseriesConfig
    images: ImagesConfig
    labels: LabelsConfig
    mechanisms: dict[str, MechanismConfig]

    @field_validator("profile")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in PROFILE_NAMES:
            raise ValueError(f"profile must be one of {PROFILE_NAMES}")
        return v

    def config_hash(self) -> str:
        """Stable hash of the full profile config for lineage manifests."""
        canonical = self.model_dump_json()
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def load_profile(name: str, configs_dir: Path | None = None) -> Profile:
    configs_dir = configs_dir or Path("configs/data")
    path = configs_dir / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"unknown data profile {name!r} (expected {path})")
    raw = yaml.safe_load(path.read_text())
    return Profile(**raw)
