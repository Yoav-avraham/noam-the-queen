"""Runtime configuration for the rest API service."""

from __future__ import annotations

import os
from dataclasses import dataclass

from stt_common.env import read_env_int, read_env_float

# Sentinel dev secret. Signing tokens with this value is insecure; use only for local
# development. Production deployments should set REST_API_TOKEN_SECRET explicitly.
# The app logs a warning at startup if REST_API_TOKEN_SECRET is set to this value.
DEFAULT_TOKEN_SECRET = "dev-insecure-secret-change-me"

DEFAULT_ORIGINS = []


def _read_env_csv(var_name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Read a comma-separated environment variable into a tuple of strings."""
    raw_value = os.getenv(var_name)
    if raw_value is None:
        return default

    values = tuple(item.strip() for item in raw_value.split(",") if item.strip())
    return values or default


@dataclass(frozen=True)
class RestApiConfig:
    """Immutable runtime configuration for the rest API service."""

    stream_api_target: str
    database_url: str
    s3_endpoint_url: str
    vllm_base_url: str
    vllm_api_key: str
    vllm_model: str
    host: str = "0.0.0.0"
    port: int = 8080
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "stt-audio"
    s3_region: str = "us-east-1"
    token_secret: str = DEFAULT_TOKEN_SECRET
    token_algorithm: str = "HS256"
    token_ttl_s: int = 3600
    # TODO: remove chunk_size_bytes,
    # chunk_duration_seconds replaces this with a dynamic logic
    # per request.
    chunk_size_bytes: int = 32 * 1024  # 32 KB
    chunk_duration_seconds: float = 60.0
    status_update_interval_s: float = 2.0
    final_result_wait_timeout_s: float = 60.0
    chunk_timeout_fraction: float = 0.2
    chunk_timeout_min_s: float = 0.1
    max_upload_bytes: int = 100 * 1024 * 1024 * 2
    upload_overall_timeout_fraction: float = 0.4
    cors_allowed_origins: tuple[str, ...] = (*DEFAULT_ORIGINS,)
    summarization_prompt_s3_key: str = "prompts/system.txt"

    def __post_init__(self) -> None:
        """Validate core settings to fail fast on bad config."""
        if self.port <= 0 or self.port > 65535:
            raise ValueError(f"port must be in 1..65535, got: {self.port}")
        if not self.token_secret:
            raise ValueError("token_secret must be a non-empty string")
        if not self.token_algorithm:
            raise ValueError("token_algorithm must be a non-empty string")
        if self.token_ttl_s <= 0:
            raise ValueError(f"token_ttl_s must be > 0, got: {self.token_ttl_s}")
        if self.chunk_size_bytes <= 0:
            raise ValueError(f"chunk_size_bytes must be > 0, got: {self.chunk_size_bytes}")
        if self.status_update_interval_s <= 0:
            raise ValueError(f"status_update_interval_s must be > 0, got: {self.status_update_interval_s}")
        if self.final_result_wait_timeout_s <= 0:
            raise ValueError(f"final_result_wait_timeout_s must be > 0, got: {self.final_result_wait_timeout_s}")
        if not (0 < self.chunk_timeout_fraction <= 1):
            raise ValueError(f"chunk_timeout_fraction must be in (0,1], got: {self.chunk_timeout_fraction})")
        if self.chunk_timeout_min_s <= 0:
            raise ValueError(f"chunk_timeout_fraction must be > 0, got: {self.chunk_timeout_fraction})")
        if not (0 < self.upload_overall_timeout_fraction <= 1):
            raise ValueError(
                f"upload_overall_timeout_fraction must be in (0,1], got: {self.upload_overall_timeout_fraction}"
            )
        if self.max_upload_bytes <= 0:
            raise ValueError(f"max_upload_bytes must be > 0, got: {self.max_upload_bytes}")

    @property
    def token_secret_is_default(self) -> bool:
        """Return True when the insecure development token secret is in use."""
        return self.token_secret == DEFAULT_TOKEN_SECRET

    @classmethod
    def from_env(cls) -> RestApiConfig:
        """Build configuration from environment variables.

        The critical secrets/connection vars ``DATABASE_URL``,
        ``REST_API_TOKEN_SECRET``, ``REST_API_S3_ACCESS_KEY``, and
        ``REST_API_S3_SECRET_KEY`` are required and raise ``KeyError`` when
        unset; all other settings fall back to their dataclass defaults.

        Returns:
            RestApiConfig populated from env vars.
        """
        return cls(
            host=os.getenv("REST_API_HOST", cls.host),
            port=read_env_int("REST_API_PORT", cls.port),
            stream_api_target=os.getenv("REST_API_STREAM_API_TARGET", "localhost:50051"),
            database_url=os.environ["DATABASE_URL"],
            s3_endpoint_url=os.getenv("REST_API_S3_ENDPOINT_URL", "http://localhost:9000"),
            s3_access_key=os.environ["REST_API_S3_ACCESS_KEY"],
            s3_secret_key=os.environ["REST_API_S3_SECRET_KEY"],
            s3_bucket=os.getenv("REST_API_S3_BUCKET", cls.s3_bucket),
            s3_region=os.getenv("REST_API_S3_REGION", cls.s3_region),
            token_secret=os.environ["REST_API_TOKEN_SECRET"],
            token_algorithm=os.getenv("REST_API_TOKEN_ALGORITHM", cls.token_algorithm),
            token_ttl_s=read_env_int("REST_API_TOKEN_TTL_S", cls.token_ttl_s),
            chunk_size_bytes=read_env_int("REST_API_CHUNK_SIZE_BYTES", cls.chunk_size_bytes),
            status_update_interval_s=read_env_float(
                "REST_API_STATUS_UPDATE_INTERVAL_S",
                cls.status_update_interval_s,
            ),
            final_result_wait_timeout_s=read_env_float(
                "REST_API_FINAL_RESULT_WAIT_TIMEOUT_S",
                cls.final_result_wait_timeout_s,
            ),
            chunk_timeout_fraction=read_env_float("REST_API_CHUNK_TIMEOUT_FRACTION", cls.chunk_timeout_fraction),
            chunk_timeout_min_s=read_env_float("REST_API_CHUNK_TIMEOUT_MIN_S", cls.chunk_timeout_min_s),
            upload_overall_timeout_fraction=read_env_float(
                "REST_API_UPLOAD_OVERALL_TIMEOUT_FRACTION",
                cls.upload_overall_timeout_fraction,
            ),
            max_upload_bytes=read_env_int("REST_API_MAX_UPLOAD_BYTES", cls.max_upload_bytes),
            cors_allowed_origins=_read_env_csv("REST_API_CORS_ORIGINS", cls.cors_allowed_origins),
            summarization_prompt_s3_key=os.getenv("SUMMARIZATION_PROMPT_S3_KEY", cls.summarization_prompt_s3_key),
            vllm_base_url=os.environ["VLLM_BASE_URL"],
            vllm_api_key=os.environ["VLLM_API_KEY"],
            vllm_model=os.environ["VLLM_MODEL"],
        )
