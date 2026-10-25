from __future__ import annotations

import pytest
from pydantic import ValidationError

from ..config import StreamApiConfig


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STREAM_API_HOST", "0.0.0.0")
    monkeypatch.setenv("STREAM_API_PORT", "50051")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")


def test_settings_init_reads_reliability_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings init should parse reliability timeout and queue controls."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("STREAM_API_FINAL_RESULT_WAIT_TIMEOUT_S", "12.5")
    monkeypatch.setenv("STREAM_API_CHUNK_PERSIST_TIMEOUT_S", "9.25")
    monkeypatch.setenv("STREAM_API_FINAL_OUTPUT_POLL_BLOCK_MS", "750")
    monkeypatch.setenv("STREAM_API_OUTBOUND_QUEUE_MAXSIZE", "256")

    config = StreamApiConfig()

    assert config.final_result_wait_timeout_s == 12.5
    assert config.chunk_persist_timeout_s == 9.25
    assert config.final_output_poll_block_ms == 750
    assert config.outbound_queue_maxsize == 256


def test_settings_init_rejects_invalid_reliability_float(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid float env values should fail fast with explicit ValidationError."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("STREAM_API_FINAL_RESULT_WAIT_TIMEOUT_S", "not-a-number")

    with pytest.raises(ValidationError):
        StreamApiConfig()


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("final_result_wait_timeout_s", 0.0),
        ("chunk_persist_timeout_s", -1.0),
    ],
)
def test_config_rejects_non_positive_reliability_float_controls(
    field_name: str,
    field_value: float,
) -> None:
    """Float reliability controls must be strictly positive."""
    with pytest.raises(ValidationError):
        if field_name == "final_result_wait_timeout_s":
            StreamApiConfig(
                host="0.0.0.0",
                port=50051,
                redis_url="redis://localhost:6379",
                final_result_wait_timeout_s=field_value,
            )

        else:
            StreamApiConfig(
                host="0.0.0.0",
                port=50051,
                redis_url="redis://localhost:6379",
                chunk_persist_timeout_s=field_value,
            )


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("final_output_poll_block_ms", 0),
        ("outbound_queue_maxsize", 0),
    ],
)
def test_config_rejects_non_positive_reliability_int_controls(
    field_name: str,
    field_value: int,
) -> None:
    """Integer reliability controls must be strictly positive."""
    with pytest.raises(ValidationError):
        if field_name == "final_output_poll_block_ms":
            StreamApiConfig(
                host="0.0.0.0",
                port=50051,
                redis_url="redis://localhost:6379",
                final_output_poll_block_ms=field_value,
            )

        else:
            StreamApiConfig(
                host="0.0.0.0",
                port=50051,
                redis_url="redis://localhost:6379",
                outbound_queue_maxsize=field_value,
            )


def test_settings_init_ignores_removed_audio_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Removed sample audio settings should no longer affect config parsing."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("STREAM_API_SAMPLE_RATE_HZ", "44100")
    monkeypatch.setenv("STREAM_API_SAMPLE_LAYOUT", "stereo")
    monkeypatch.setenv("STREAM_API_SAMPLE_CODEC", "pcm_f32le")
    monkeypatch.setenv("STREAM_API_SAMPLE_CHANNELS", "2")

    config = StreamApiConfig()

    assert config.redis_url == "redis://localhost:6379"


@pytest.mark.parametrize(
    "missing_var",
    ["STREAM_API_HOST", "STREAM_API_PORT", "REDIS_URL"],
)
def test_settings_init_rejects_missing_required_service_settings(
    monkeypatch: pytest.MonkeyPatch,
    missing_var: str,
) -> None:
    """Core service settings should be required in the environment."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv(missing_var)

    with pytest.raises(ValidationError):
        StreamApiConfig()
