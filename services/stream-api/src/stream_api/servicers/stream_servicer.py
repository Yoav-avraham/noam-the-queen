"""AudioIngest servicer for stream ingestion."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from collections.abc import AsyncIterator

import grpc

from ..proto import audio_ingest_pb2 as pb2
from ..proto import audio_ingest_pb2_grpc as pb2_grpc
from ..types import ServerEventQueue
from ..ingest.session_processor import SessionProcessor


class AudioIngestServicer(pb2_grpc.AudioIngestServiceServicer):
    """Thin gRPC adapter bridging client audio streams to a ``SessionProcessor``."""

    def __init__(
        self,
        *,
        session_processor: SessionProcessor,
        outbound_queue_maxsize: int,
    ) -> None:
        """Initialize the servicer with its session processor and queue bound.

        Args:
            session_processor: Owns the per-session ingest/route lifecycle.
            outbound_queue_maxsize: Max buffered outbound events per stream.
        """
        if outbound_queue_maxsize <= 0:
            raise ValueError(f"outbound_queue_maxsize must be > 0, got: {outbound_queue_maxsize}")

        self._session_processor = session_processor
        self._outbound_queue_maxsize = outbound_queue_maxsize

    async def StreamAudio(
        self,
        request_iterator: AsyncIterator[pb2.AudioChunk],
        _context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[pb2.ServerEvent]:
        """Consume continuous audio chunks and emit server events.

        Client sends: stream of AudioChunk { bytes audio = 1; string session_id = 2; }
        Server sends: initial StreamAck with session_id, then result events routed
        from Redis final_output.

        Args:
            request_iterator: Inbound audio chunks.
            _context: Reserved gRPC context argument required by the interface.

        Yields:
            ServerEvent messages: StreamAck (initial), StreamError (on failure),
            ConsumerResultEvent (from final_output), then OK close.
        """
        outbound_queue: ServerEventQueue = asyncio.Queue(maxsize=self._outbound_queue_maxsize)
        producer = asyncio.create_task(
            self._session_processor.consume_client_stream(
                request_iterator=request_iterator,
                outbound_queue=outbound_queue,
            )
        )

        try:
            while True:
                outbound_event = await outbound_queue.get()

                if outbound_event is None:
                    break

                yield outbound_event
        finally:
            if not producer.done():
                producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer
