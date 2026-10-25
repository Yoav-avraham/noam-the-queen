"""Async gRPC client for stream-api's ``AudioIngestService.StreamAudio``.

This module is the only place that touches the generated protobuf stubs. It
exposes a small typed event union (:data:`StreamEvent`) so the rest of the
service never imports protobuf types directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import logging
from collections.abc import AsyncIterator

import grpc

from .types import StreamAck, StreamEvent, StreamResult, StreamFailure
from ..proto import audio_ingest_pb2 as pb2
from ..proto import audio_ingest_pb2_grpc as pb2_grpc
from ..domain import ErrorKey, RestApiError

if TYPE_CHECKING:
    from collections.abc import AsyncIterable

logger = logging.getLogger(__name__)


def create_channel(target: str) -> grpc.aio.Channel:
    """Open an insecure async gRPC channel to stream-api.

    stream-api listens with ``add_insecure_port`` (no TLS), so the client uses
    an insecure channel to match.
    """
    return grpc.aio.insecure_channel(target)


class StreamAudioClient:
    """Thin wrapper over the StreamAudio bidirectional streaming RPC."""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        self._stub = pb2_grpc.AudioIngestServiceStub(channel)

    async def stream_audio(
        self,
        chunks: AsyncIterable[bytes],
        *,
        channels: int,
        sample_width: int,
        sample_rate: int,
    ) -> AsyncIterator[StreamEvent]:
        """Stream audio chunks upstream and yield typed server events.

        Args:
            chunks: Async iterable of raw audio byte chunks to send.
            channels: Number of audio channels, forwarded unchanged on each chunk.
            sample_width: Sample width in bytes, forwarded unchanged on each chunk.
            sample_rate: Sample rate in Hz, forwarded unchanged on each chunk.

        Yields:
            :class:`StreamAck`, :class:`StreamResult`, or :class:`StreamFailure`.

        Raises:
            RestApiError: ``UPSTREAM_STREAM_FAILURE`` if the RPC aborts.
        """

        async def _requests() -> AsyncIterator[pb2.AudioChunk]:
            async for chunk in chunks:
                yield pb2.AudioChunk(
                    audio=chunk,
                    channels=channels,
                    sample_width=sample_width,
                    sample_rate=sample_rate,
                )

        call = self._stub.StreamAudio(_requests())
        try:
            async for event in call:
                converted = _convert_event(event)
                if converted is not None:
                    yield converted
        except grpc.aio.AioRpcError as exc:
            logger.error(
                "stream-api StreamAudio RPC failed",
                extra={"code": str(exc.code()), "detail": exc.details()},
            )
            raise RestApiError(key=ErrorKey.UPSTREAM_STREAM_FAILURE) from exc


def _convert_event(event: pb2.ServerEvent) -> StreamEvent | None:
    """Convert a protobuf ServerEvent into a typed event (or None if unknown)."""
    kind = event.WhichOneof("event")
    if kind == "ack":
        return StreamAck(session_id=event.ack.session_id, status=event.ack.status)
    if kind == "result":
        result = event.result
        return StreamResult(
            session_id=result.session_id,
            text=result.partial_text,
            is_final=result.is_final,
        )
    if kind == "error":
        return StreamFailure(code=event.error.code, message=event.error.message)
    logger.warning("received unknown server event kind", extra={"kind": kind})
    return None
