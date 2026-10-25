"""Application context and FastAPI dependency providers.

The :class:`AppContext` holds the service's long-lived collaborators (config,
persistence store, object storage, and a factory for per-stream gRPC clients).
It is built once at startup and attached to ``app.state`` so request handlers can
resolve dependencies without global singletons. Tests inject a context with fake
collaborators instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import logging
from dataclasses import dataclass
from collections.abc import Callable

from fastapi import Request

from rest_api.storage.prompt_repository import PromptRepository

from .db import SessionStore, SqlAlchemySessionStore, create_engine, create_sessionmaker
from .config import RestApiConfig
from .storage import AudioObjectStorage
from .pipeline import StreamAudioClient, create_channel

if TYPE_CHECKING:
    import grpc
    from sqlalchemy.ext.asyncio import AsyncEngine

    from .summary.summarization_service import SummarizationService

logger = logging.getLogger(__name__)

StreamClientFactory = Callable[[], StreamAudioClient]


@dataclass(slots=True)
class AppContext:
    """Long-lived collaborators shared across requests."""

    config: RestApiConfig
    store: SessionStore
    storage: AudioObjectStorage
    prompt_repository: PromptRepository
    stream_client_factory: StreamClientFactory
    summarization_service: SummarizationService
    channel: grpc.aio.Channel | None = None
    engine: AsyncEngine | None = None

    async def aclose(self) -> None:
        """Release owned infrastructure resources (channel, engine)."""
        if self.channel is not None:
            await self.channel.close(grace=None)
        if self.engine is not None:
            await self.engine.dispose()


async def build_context(config: RestApiConfig) -> AppContext:
    """Construct a production :class:`AppContext` from configuration."""
    from .summary.vllm_client import VLLMClient
    from .summary.summarization_service import SummarizationService

    engine = create_engine(config.database_url)
    sessionmaker = create_sessionmaker(engine)
    store = SqlAlchemySessionStore(sessionmaker)
    storage = AudioObjectStorage(
        endpoint_url=config.s3_endpoint_url,
        access_key=config.s3_access_key,
        secret_key=config.s3_secret_key,
        bucket=config.s3_bucket,
        region=config.s3_region,
        verify=False,
    )
    prompt_repository = PromptRepository(
        endpoint_url=config.s3_endpoint_url,
        access_key=config.s3_access_key,
        secret_key=config.s3_secret_key,
        bucket=config.s3_bucket,
        region=config.s3_region,
        verify=False,
    )
    channel = create_channel(config.stream_api_target)

    def stream_client_factory() -> StreamAudioClient:
        return StreamAudioClient(channel)

    vllm_client = VLLMClient(base_url=config.vllm_base_url, api_key=config.vllm_api_key)
    summarization_service = SummarizationService(
        client=vllm_client.client,
        model_name=config.vllm_model,
    )

    return AppContext(
        config=config,
        store=store,
        storage=storage,
        prompt_repository=prompt_repository,
        stream_client_factory=stream_client_factory,
        summarization_service=summarization_service,
        channel=channel,
        engine=engine,
    )


def get_context(request: Request) -> AppContext:
    """Resolve the application context attached to the running app."""
    return request.app.state.context


def get_config(request: Request) -> RestApiConfig:
    """Dependency: resolve the runtime configuration."""
    return get_context(request).config


def get_store(request: Request) -> SessionStore:
    """Dependency: resolve the session persistence store."""
    return get_context(request).store
