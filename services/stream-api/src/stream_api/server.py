"""Server bootstrap for the stream API service."""

from __future__ import annotations

import asyncio
import logging

import grpc

from stt_common.redis_stream_client import RedisStreamClient

from .proto import audio_ingest_pb2_grpc as pb2_grpc
from .config import StreamApiConfig
from .ingest import StreamRouter, SessionProcessor
from .servicers import AudioIngestServicer


async def serve(config: StreamApiConfig | None = None) -> None:
    """Start and run the stream API gRPC server.

    Args:
        config: Optional runtime configuration. Loaded from environment when omitted.
    """
    config = config or StreamApiConfig()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    redis_client = RedisStreamClient.from_url(config.redis_url)
    await redis_client.ping()

    router = StreamRouter()
    session_processor = SessionProcessor(
        redis_client=redis_client,
        router=router,
        chunk_persist_timeout_s=config.chunk_persist_timeout_s,
        final_result_wait_timeout_s=config.final_result_wait_timeout_s,
        final_output_poll_block_ms=config.final_output_poll_block_ms,
    )

    server = grpc.aio.server()
    pb2_grpc.add_AudioIngestServiceServicer_to_server(
        AudioIngestServicer(
            session_processor=session_processor,
            outbound_queue_maxsize=config.outbound_queue_maxsize,
        ),
        server,
    )
    server.add_insecure_port(f"{config.host}:{config.port}")

    await server.start()
    logging.getLogger(__name__).info(
        "stream api listening on %s:%s",
        config.host,
        config.port,
        extra={"redis_host": redis_client.redis_hostname},
    )
    try:
        await server.wait_for_termination()
    finally:
        await redis_client.aclose()


def main() -> None:
    """Run the async server entrypoint."""
    asyncio.run(serve())
