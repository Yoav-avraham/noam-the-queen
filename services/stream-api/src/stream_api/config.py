"""Runtime configuration for the stream API service."""

from __future__ import annotations

from typing import Any, overload

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

MAX_PORT = 65535


class StreamApiConfig(BaseSettings):
    """Immutable runtime configuration for the stream API service."""

    model_config = SettingsConfigDict(
        env_prefix="STREAM_API_",
        extra="ignore",
        populate_by_name=True,
        frozen=True,
    )

    host: str
    port: int = Field(ge=1, le=MAX_PORT)
    redis_url: str = Field(validation_alias="REDIS_URL")
    final_result_wait_timeout_s: float = Field(default=12.0, gt=0)
    chunk_persist_timeout_s: float = Field(default=3.0, gt=0)
    final_output_poll_block_ms: int = Field(default=1000, gt=0)
    outbound_queue_maxsize: int = Field(default=1024, gt=0)

    @overload
    def __init__(self) -> None: ...

    @overload
    def __init__(
        self,
        *,
        host: str,
        port: int,
        redis_url: str,
        final_result_wait_timeout_s: float = 12.0,
        chunk_persist_timeout_s: float = 3.0,
        final_output_poll_block_ms: int = 1000,
        outbound_queue_maxsize: int = 1024,
    ) -> None: ...

    def __init__(self, **values: Any) -> None:
        """Preserve BaseSettings env loading while keeping typed constructor hints."""
        super().__init__(**values)
