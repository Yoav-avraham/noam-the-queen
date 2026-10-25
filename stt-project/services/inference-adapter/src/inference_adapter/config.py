from __future__ import annotations

import os
from dataclasses import dataclass

TRITON_URL_ENV_VAR = "TRITON_URL"
REDIS_URL_ENV_VAR = "REDIS_URL"
CONSUMER_GROUP_NAME_ENV_VAR = "INFERENCE_ADAPTER_CONSUMER_GROUP_NAME"
DEFAULT_CONSUMER_GROUP_NAME = "inference-adapter-workers"


@dataclass(frozen=True, slots=True)
class InferenceAdapterConfig:
    """Runtime configuration for the inference adapter service."""

    redis_url: str
    triton_url: str
    consumer_group_name: str = DEFAULT_CONSUMER_GROUP_NAME

    @classmethod
    def from_env(cls) -> InferenceAdapterConfig:
        """Build config from environment variables.

        Raises:
                RuntimeError: If required environment variables are missing.
        """
        redis_url = os.getenv(REDIS_URL_ENV_VAR)
        triton_url = os.getenv(TRITON_URL_ENV_VAR)

        if not redis_url:
            raise RuntimeError(f"missing required environment variable: {REDIS_URL_ENV_VAR}")

        if not triton_url:
            raise RuntimeError(f"missing required environment variable: {TRITON_URL_ENV_VAR}")

        return cls(
            redis_url=redis_url,
            triton_url=triton_url,
            consumer_group_name=os.getenv(
                CONSUMER_GROUP_NAME_ENV_VAR,
                DEFAULT_CONSUMER_GROUP_NAME,
            ),
        )
