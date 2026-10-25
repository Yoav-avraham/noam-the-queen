"""Process entry point for the synchronizer service."""

from __future__ import annotations

from typing import cast
import asyncio
import logging
import json

from stt_common.contracts import (
    StreamName,
    ServiceOutput,
    FinalOutputWindowContent,
    TritonOutputWindowContent,
)
from stt_common.stream_manager import StreamManager, ServiceHandler
from stt_common.redis_stream_client import RedisStreamClient

from .config import SynchronizerConfig
from .localization import configure_i18n
from .transcript_merger import TranscriptMerger
from .types import MergedTranscript

logger = logging.getLogger(__name__)


def configure_process() -> None:
    """Perform one-time, process-wide startup setup.

    Centralizes everything the running service needs before serving — logging,
    i18n catalogs, and any future setup — so the process is bootstrapped from a
    single place. Unit tests do not run this path; components that need a given
    facility (for example the transcript merger and i18n) ensure their own
    prerequisites so they stay independently testable.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    configure_i18n()


def build_stream_handler(transcript_merger: TranscriptMerger) -> ServiceHandler:
    """Build the stream handler used by StreamManager."""

    async def handle_stream_data(source: ServiceOutput) -> dict[str, str]:
        merged: MergedTranscript = transcript_merger.merge_window(
            session_id=source.session_id,
            content=cast(TritonOutputWindowContent, source.window_payload.content),
            locale=source.window_payload.locale,
            is_final=source.is_final,
        )
        logger.info(
            (
                f"merged synchronizer window ",
                f"session_id: {source.session_id} ",
                f"sequence_id: {source.sequence_id} ",
                f"is_final: {source.is_final} "
            )
        )

        output_content: FinalOutputWindowContent = {"text": json.dumps(merged.transcript_object)}
        output_dict: list[dict[str, str]] = merged.transcript_object
        return cast(dict[str, str], output_content)

    return handle_stream_data


async def serve() -> None:
    """Start and run the synchronizer service."""
    redis_client: RedisStreamClient | None = None
    try:
        configure_process()
        logger.info("synchronizer process configured")
        config = SynchronizerConfig()
        transcript_merger = TranscriptMerger()
        redis_client = RedisStreamClient.from_url(config.redis_url)
        manager = StreamManager(
            redis_client=redis_client,
            consumer_group_name=config.consumer_group_name,
            input_stream_name=StreamName.TRITON_OUTPUT,
            service_handler=build_stream_handler(transcript_merger),
        )
        await manager.check_redis_connection()
        await manager.run_workers()
    except Exception:
        logger.exception("synchronizer process terminated with error")
        raise
    finally:
        if redis_client is not None:
            await redis_client.aclose()


def main() -> None:
    """Run the async service entry point."""
    asyncio.run(serve())
