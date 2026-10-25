"""Tests for RestApiConfig loading and validation."""

from __future__ import annotations

import pytest

from rest_api.config import RestApiConfig

# Env vars that from_env() requires; tests exercising the env path must set them
# unless they specifically assert the missing-var behavior.
_REQUIRED_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/x",
    "REST_API_TOKEN_SECRET": "strong-secret",
    "REST_API_S3_ACCESS_KEY": "access",
    "REST_API_S3_SECRET_KEY": "secret",
    "VLLM_BASE_URL": "http://vllm:8000/v1",
    "VLLM_API_KEY": "test-key",
    "VLLM_MODEL": "llama-3.1-8b-instruct",
}


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)


def test_defaults_are_valid() -> None:
    config = RestApiConfig(
        stream_api_target="localhost:50051",
        database_url="postgresql+asyncpg://user:pass@localhost/db",
        s3_endpoint_url="http://localhost:9000",
        vllm_base_url="http://vllm:8000/v1",
        vllm_api_key="test-key",
        vllm_model="llama-3.1-8b-instruct",
    )
    assert config.port == 8080
    assert config.token_algorithm == "HS256"
    assert config.token_secret_is_default is True


def test_from_env_reads_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("REST_API_PORT", "9090")
    monkeypatch.setenv("REST_API_STATUS_UPDATE_INTERVAL_S", "5")

    config = RestApiConfig.from_env()

    assert config.port == 9090
    assert config.token_secret == "strong-secret"
    assert config.token_secret_is_default is False
    assert config.database_url.endswith("/x")
    assert config.status_update_interval_s == 5.0


@pytest.mark.parametrize("missing", sorted(_REQUIRED_ENV))
def test_from_env_requires_critical_vars(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(KeyError, match=missing):
        RestApiConfig.from_env()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("port", 0),
        ("port", 70000),
        ("token_secret", ""),
        ("token_ttl_s", 0),
        ("chunk_size_bytes", 0),
        ("status_update_interval_s", 0.0),
        ("final_result_wait_timeout_s", -1.0),
        ("upload_overall_timeout_fraction", 0.0),
        ("upload_overall_timeout_fraction", 1.5),
        ("max_upload_bytes", 0),
    ],
)
def test_invalid_values_raise(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        RestApiConfig(
            stream_api_target="localhost:50051",
            database_url="postgresql+asyncpg://u:p@localhost/db",
            s3_endpoint_url="http://localhost:9000",
            vllm_base_url="http://vllm:8000/v1",
            vllm_api_key="test-key",
            vllm_model="llama-3.1-8b-instruct",
            **{field: value},  # type: ignore[arg-type]
        )


def test_from_env_rejects_non_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("REST_API_PORT", "not-a-number")
    with pytest.raises(ValueError, match="REST_API_PORT"):
        RestApiConfig.from_env()


def test_from_env_rejects_non_float(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("REST_API_STATUS_UPDATE_INTERVAL_S", "fast")
    with pytest.raises(ValueError, match="REST_API_STATUS_UPDATE_INTERVAL_S"):
        RestApiConfig.from_env()
