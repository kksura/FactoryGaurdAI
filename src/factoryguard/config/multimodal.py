"""Typed loader for ``configs/models/multimodal.yaml`` (spec §17)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from factoryguard.inference.serving import ServingMode


class TsEncoderConfig(BaseModel):
    length: int = Field(default=128, ge=16)
    embed_dim: int = Field(default=64, ge=8)
    epochs: int = Field(default=15, ge=1)
    ssl_pretrain: bool = False
    ssl_epochs: int = Field(default=10, ge=1)
    batch_size: int = Field(default=256, ge=8)
    lr: float = Field(default=1e-3, gt=0)


class GraphConfig(BaseModel):
    half_life_days: float = Field(default=7.0, gt=0)
    smoothing: float = Field(default=25.0, gt=0)


class FusionConfig(BaseModel):
    modality_dropout: float = Field(default=0.3, ge=0, le=0.9)
    dropout_copies: int = Field(default=2, ge=0)
    proj_dim: int = Field(default=32, ge=4)
    epochs: int = Field(default=60, ge=1)
    lr: float = Field(default=3e-3, gt=0)


class CalibrationConfig(BaseModel):
    min_isotonic_n: int = Field(default=200, ge=10)


class UncertaintyConfig(BaseModel):
    conformal_alpha: float = Field(default=0.1, gt=0, lt=0.5)
    ood_quantile: float = Field(default=0.995, gt=0.5, lt=1.0)
    ood_shrinkage: float = Field(default=0.1, ge=0, le=1.0)


class ServingConfig(BaseModel):
    mode: ServingMode = ServingMode.SUPERVISED
    blend_weight: float = Field(default=0.7, ge=0, le=1.0)


class RetrievalConfig(BaseModel):
    k: int = Field(default=5, ge=1)


class RootCauseConfig(BaseModel):
    half_life_days: float = Field(default=14.0, gt=0)


class MultimodalConfig(BaseModel):
    ts_encoder: TsEncoderConfig = TsEncoderConfig()
    graph: GraphConfig = GraphConfig()
    fusion: FusionConfig = FusionConfig()
    calibration: CalibrationConfig = CalibrationConfig()
    uncertainty: UncertaintyConfig = UncertaintyConfig()
    serving: ServingConfig = ServingConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    root_cause: RootCauseConfig = RootCauseConfig()


def load_multimodal_config(path: Path | None = None) -> MultimodalConfig:
    path = path or Path("configs/models/multimodal.yaml")
    raw = yaml.safe_load(path.read_text()) or {}
    return MultimodalConfig.model_validate(raw)
