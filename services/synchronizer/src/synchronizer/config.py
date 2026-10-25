from __future__ import annotations

from typing import Any, overload

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONSUMER_GROUP_NAME = "synchronizer-workers"


class SynchronizerConfig(BaseSettings):
    """Runtime configuration for the synchronizer service."""

    model_config = SettingsConfigDict(
        env_prefix="SYNCHRONIZER_",
        extra="ignore",
        populate_by_name=True,
        frozen=True,
    )

    redis_url: str = Field(validation_alias="REDIS_URL")
    consumer_group_name: str = Field(default=DEFAULT_CONSUMER_GROUP_NAME)

    @overload
    def __init__(self) -> None: ...

    @overload
    def __init__(
        self,
        *,
        redis_url: str,
        consumer_group_name: str = DEFAULT_CONSUMER_GROUP_NAME,
    ) -> None: ...

    def __init__(self, **values: Any) -> None:
        """Preserve BaseSettings env loading while keeping typed constructor hints."""
        super().__init__(**values)
