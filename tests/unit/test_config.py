"""Configuration layering and fail-closed production validation."""

from pathlib import Path

import pytest

from factoryguard.config import ConfigurationError, Environment, Settings, load_settings

CONFIGS = Path(__file__).resolve().parents[2] / "configs" / "environments"


def test_defaults_are_secure() -> None:
    s = Settings()
    assert s.environment is Environment.LOCAL
    assert s.auth.enabled is True
    assert s.api.debug is False
    assert s.api.host == "127.0.0.1"
    assert s.api.cors_allowed_origins == []  # deny by default
    assert s.storage.public_access is False
    assert s.model.verify_checksums is True


def test_load_test_environment() -> None:
    s = load_settings("test", configs_dir=CONFIGS)
    assert s.environment is Environment.TEST
    assert s.monitoring.log_format == "json"


def test_unknown_environment_rejected() -> None:
    with pytest.raises(ConfigurationError, match="unknown environment"):
        load_settings("prod-ish", configs_dir=CONFIGS)


def test_env_var_overrides_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FG_MONITORING__LOG_LEVEL", "DEBUG")
    s = load_settings("test", configs_dir=CONFIGS)
    assert s.monitoring.log_level == "DEBUG"


def test_production_template_fails_without_secrets() -> None:
    # The committed production template alone (no Key Vault-injected env vars)
    # must be rejected: empty credentials are forbidden in hardened envs.
    with pytest.raises(ConfigurationError):
        load_settings("production", configs_dir=CONFIGS)


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"api": {"debug": True}}, "debug"),
        ({"auth": {"enabled": False}}, "auth.enabled"),
        ({"auth": {"provider": "local-jwt"}}, "local-jwt"),
        ({"storage": {"public_access": True}}, "public_access"),
        ({"database": {"sslmode": "disable"}}, "sslmode"),
        ({"database": {"password": "admin"}}, "default credential"),
        ({"model": {"verify_checksums": False}}, "verify_checksums"),
        ({"model": {"serving_alias": "candidate"}}, "champion"),
        ({"api": {"cors_allowed_origins": ["*"]}}, "CORS"),
    ],
)
def test_hardened_env_rejects_insecure_combinations(overrides: dict, fragment: str) -> None:
    secure = {
        "environment": "production",
        "api": {"debug": False, "docs_enabled": False},
        "auth": {"enabled": True, "provider": "entra-id"},
        "database": {"sslmode": "require", "password": "kv-injected-3f9c"},
        "storage": {
            "backend": "azure-blob",
            "public_access": False,
            "secret_key": "kv-injected-8ab2",
        },
    }
    merged = {**secure}
    for key, sub in overrides.items():
        merged[key] = {**secure.get(key, {}), **sub}
    with pytest.raises(ConfigurationError, match=fragment):
        Settings(**merged)


def test_secure_production_configuration_accepted() -> None:
    s = Settings(
        environment="production",
        api={"debug": False, "docs_enabled": False},
        auth={"enabled": True, "provider": "entra-id"},
        database={"sslmode": "require", "password": "kv-injected-3f9c"},
        storage={
            "backend": "azure-blob",
            "public_access": False,
            "secret_key": "kv-injected-8ab2",
        },
    )
    assert s.environment.is_hardened
