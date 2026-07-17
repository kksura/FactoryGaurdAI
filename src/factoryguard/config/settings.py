"""Layered configuration with fail-closed production validation.

Layers (later wins):
  1. Secure defaults defined on the models below
  2. ``configs/environments/<env>.yaml``
  3. Environment variables (prefix ``FG_``, nested delimiter ``__``)

Production startup MUST fail when an insecure combination is detected; there
is no silent fallback from production to development behavior (spec §17).
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Credentials that must never survive into staging/production.
_FORBIDDEN_CREDENTIALS = frozenset(
    {"", "changeme", "change-me", "password", "admin", "minioadmin", "postgres", "dev-secret"}
)


class ConfigurationError(Exception):
    """Configuration is invalid or insecure for the selected environment."""


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_hardened(self) -> bool:
        """Environments in which insecure settings must abort startup."""
        return self in (Environment.STAGING, Environment.PRODUCTION)


class ApiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    debug: bool = False
    docs_enabled: bool = True
    max_request_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    rate_limit_per_minute: int = Field(default=120, ge=1)
    request_timeout_seconds: float = Field(default=30.0, gt=0)
    cors_allowed_origins: list[str] = Field(default_factory=list)  # deny by default


class AuthConfig(BaseModel):
    enabled: bool = True
    provider: str = "local-jwt"  # local-jwt | entra-id
    issuer: str = "factoryguard-local"
    audience: str = "factoryguard-api"
    # Dev-only HMAC secret for the local JWT provider. In staging/production the
    # provider must be entra-id (asymmetric keys fetched from the IdP).
    local_jwt_secret: str = ""
    token_ttl_seconds: int = Field(default=3600, ge=60)


class DatabaseConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 5432
    database: str = "factoryguard"
    user: str = "factoryguard"
    password: str = ""
    sslmode: str = "prefer"  # forced to require in hardened envs

    def dsn(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/"
            f"{self.database}?sslmode={self.sslmode}"
        )


class StorageConfig(BaseModel):
    backend: str = "filesystem"  # filesystem | s3 | azure-blob
    root_path: Path = Path("data")
    endpoint_url: str = ""  # MinIO/S3 endpoint for backend=s3
    bucket: str = "factoryguard"
    access_key: str = ""
    secret_key: str = ""
    public_access: bool = False  # must never be true in hardened envs


class MlflowConfig(BaseModel):
    tracking_uri: str = "file:./mlruns"
    experiment: str = "factoryguard"
    registry_path: Path = Path("artifacts/registry")


class ModelConfig(BaseModel):
    # Which registry alias serves predictions; hardened envs require champion.
    serving_alias: str = "champion"
    require_approval: bool = True
    verify_checksums: bool = True
    abstain_uncertainty_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    abstain_disagreement_threshold: float = Field(default=0.35, ge=0.0, le=1.0)


class MonitoringConfig(BaseModel):
    metrics_enabled: bool = True
    otel_endpoint: str = ""  # empty = console/no-op exporter
    log_level: str = "INFO"
    log_format: str = "json"  # json | console


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FG_",
        env_nested_delimiter="__",
        extra="forbid",
        frozen=True,
    )

    environment: Environment = Environment.LOCAL
    schema_version: str = "1.0"
    api: ApiConfig = ApiConfig()
    auth: AuthConfig = AuthConfig()
    database: DatabaseConfig = DatabaseConfig()
    storage: StorageConfig = StorageConfig()
    mlflow: MlflowConfig = MlflowConfig()
    model: ModelConfig = ModelConfig()
    monitoring: MonitoringConfig = MonitoringConfig()

    @model_validator(mode="after")
    def _fail_closed(self) -> Self:
        if not self.environment.is_hardened:
            return self
        problems: list[str] = []
        if self.api.debug:
            problems.append("api.debug must be false")
        if self.api.docs_enabled:
            problems.append("api.docs_enabled must be false (no public OpenAPI UI)")
        if not self.auth.enabled:
            problems.append("auth.enabled must be true")
        if self.auth.provider == "local-jwt":
            problems.append("auth.provider must not be the dev local-jwt provider")
        if self.storage.public_access:
            problems.append("storage.public_access must be false")
        if self.storage.backend == "filesystem":
            problems.append("storage.backend must be a managed object store")
        if self.database.sslmode not in ("require", "verify-ca", "verify-full"):
            problems.append("database.sslmode must require TLS")
        for label, value in (
            ("database.password", self.database.password),
            ("storage.secret_key", self.storage.secret_key),
            ("auth.local_jwt_secret", self.auth.local_jwt_secret or "unused-ok"),
        ):
            if value.lower() in _FORBIDDEN_CREDENTIALS:
                problems.append(f"{label} is empty or a known default credential")
        if not self.model.verify_checksums:
            problems.append("model.verify_checksums must be true")
        if not self.model.require_approval:
            problems.append("model.require_approval must be true")
        if self.model.serving_alias != "champion":
            problems.append("model.serving_alias must be 'champion' (approved model only)")
        if self.api.cors_allowed_origins == ["*"]:
            problems.append("CORS wildcard origin is forbidden")
        if problems:
            raise ConfigurationError(
                f"insecure configuration for environment={self.environment.value}: "
                + "; ".join(problems)
            )
        return self


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(environment: str | None = None, configs_dir: Path | None = None) -> Settings:
    """Load settings for ``environment`` (default: ``FG_ENVIRONMENT`` or local).

    YAML file provides the middle layer; process environment variables
    (handled by pydantic-settings) override YAML via init precedence rules:
    env vars win because Settings reads them itself and we only pass YAML
    values for fields the YAML defines and env does not.
    """
    env_name = (environment or os.environ.get("FG_ENVIRONMENT") or "local").lower()
    try:
        env = Environment(env_name)
    except ValueError as exc:
        raise ConfigurationError(f"unknown environment: {env_name!r}") from exc

    configs_dir = configs_dir or Path("configs/environments")
    yaml_path = configs_dir / f"{env.value}.yaml"
    file_layer: dict[str, Any] = {}
    if yaml_path.is_file():
        loaded = yaml.safe_load(yaml_path.read_text()) or {}
        if not isinstance(loaded, dict):
            raise ConfigurationError(f"{yaml_path} must contain a mapping")
        file_layer = loaded

    # Environment variables must beat YAML: drop YAML keys whose top-level
    # section has any FG_ env override for the exact nested field.
    init_layer = _deep_merge({"environment": env.value}, file_layer)
    try:
        return Settings(**_strip_env_overridden(init_layer))
    except ConfigurationError:
        raise
    except Exception as exc:  # pydantic ValidationError → uniform error type
        raise ConfigurationError(str(exc)) from exc


def _strip_env_overridden(layer: dict[str, Any], prefix: str = "FG_") -> dict[str, Any]:
    """Remove keys from the YAML layer that are overridden via environment vars."""
    result: dict[str, Any] = {}
    for key, value in layer.items():
        env_key = f"{prefix}{key.upper()}"
        if isinstance(value, dict):
            nested = _strip_env_overridden(value, prefix=f"{env_key}__")
            if nested:
                result[key] = nested
        elif env_key not in os.environ:
            result[key] = value
    return result
