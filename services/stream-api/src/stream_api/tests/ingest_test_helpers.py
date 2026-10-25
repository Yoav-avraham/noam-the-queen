from __future__ import annotations

from typing import Any
import asyncio
from dataclasses import dataclass
from collections.abc import AsyncIterator

import grpc
import numpy as np

from stt_common.contracts import (
    ACTIVE_STREAMS_KEY,
    StreamName,
    ServiceOutput,
    WindowPayload,
    ReadyAudioWindowContent,
    session_stream_key,
)
from stt_common.redis_stream_client import RedisStreamClient

from ..proto import audio_ingest_pb2 as pb2
from ..ingest import StreamRouter, SessionProcessor
from ..servicers import AudioIngestServicer


@dataclass(frozen=True)
class PersistedChunk:
    """Decoded view of one ready-audio chunk written to the fake Redis."""

    session_id: str
    sequence_number: int
    is_final: bool
    audio: bytes


class FakeContext:
    """Mock gRPC service context that captures abort calls for testing."""

    def __init__(self) -> None:
        """Initialize FakeContext with no abort code or details."""
        self.code: grpc.StatusCode | None = None
        self.details: str | None = None

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        """Simulate gRPC stream abort by capturing code and details, then raising exception.

        Args:
            code: The gRPC status code for the abort.
            details: The error message details.

        Raises:
            AbortCalled: Always raised to signal abort was called.
        """
        self.code = code
        self.details = details
        raise AbortCalled(details)

    def set_code(self, code: grpc.StatusCode) -> None:
        """Set the gRPC status code for the context."""
        self.code = code

    def set_details(self, details: str) -> None:
        """Set the gRPC status details for the context."""
        self.details = details


class AbortCalled(Exception):
    """Exception raised when FakeContext.abort() is called."""


class FakeRawRedis:
    """In-memory async Redis double wrapped by a real ``RedisStreamClient``.

    Captures active-session announcements and ready-audio chunk persistence, and
    serves per-session ``final_output`` entries to the polling consumer.
    """

    def __init__(
        self,
        *,
        fail_chunk_persist: bool = False,
        chunk_persist_delay_s: float = 0.0,
    ) -> None:
        """Initialize the fake with optional first-chunk failure or write delay."""
        self._fail_chunk_persist = fail_chunk_persist
        self._chunk_persist_delay_s = chunk_persist_delay_s
        self._streams: dict[str, list[tuple[Any, dict[bytes, bytes]]]] = {}
        self._counter = 0
        self.announcements: list[str] = []
        self.requests: list[PersistedChunk] = []
        self.ping_calls = 0
        self.closed = False

    def _next_id(self) -> bytes:
        self._counter += 1
        return f"{self._counter}-0".encode()

    async def ping(self) -> None:
        """Record a connectivity check."""
        self.ping_calls += 1

    async def aclose(self) -> None:
        """Record connection close."""
        self.closed = True

    async def xadd(self, name: str, fields: dict[Any, Any]) -> bytes:
        """Append one entry, capturing announcements and persisted chunks."""
        if name == ACTIVE_STREAMS_KEY:
            self.announcements.append(fields[RedisStreamClient.SESSION_ID_FIELD])
        else:
            data = fields.get(RedisStreamClient.DATA_FIELD)
            if data is not None:
                if self._chunk_persist_delay_s:
                    await asyncio.sleep(self._chunk_persist_delay_s)
                if self._fail_chunk_persist and not self.requests:
                    raise RuntimeError("redis unavailable")
                output = ServiceOutput.model_validate_json(data)
                content = ReadyAudioWindowContent.model_validate(output.window_payload.content)
                self.requests.append(
                    PersistedChunk(
                        session_id=output.session_id,
                        sequence_number=output.sequence_id,
                        is_final=output.is_final,
                        audio=content.raw_bytes,
                    )
                )
        entry_id = self._next_id()
        self._streams.setdefault(name, []).append((entry_id, fields))
        return entry_id

    async def xread(
        self,
        streams: dict[Any, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[Any, list[tuple[Any, dict[bytes, bytes]]]]]:
        """Serve entries newer than the cursor, blocking briefly when empty."""
        _ = count
        stream_key, last_seen_id = next(iter(streams.items()))
        last_seen = RedisStreamClient.to_str(last_seen_id)
        entries = self._streams.get(stream_key, [])
        ready = [
            (entry_id, fields)
            for entry_id, fields in entries
            if self._is_newer(RedisStreamClient.to_str(entry_id), last_seen)
        ]
        if ready:
            return [(stream_key, ready)]

        await asyncio.sleep(max(1, block or 1) / 1000)
        return []

    def add_result(
        self,
        *,
        session_id: str,
        text: str,
        is_final: bool,
        redis_id: str,
        payload_session_id: str | None = None,
    ) -> None:
        """Append one final_output entry for the given session route."""
        stream_key = session_stream_key(StreamName.FINAL_OUTPUT, session_id)
        output = ServiceOutput(
            session_id=payload_session_id or session_id,
            sequence_id=1,
            is_final=is_final,
            window_payload=WindowPayload(content={"text": text}),
        )
        self._streams.setdefault(stream_key, []).append((redis_id, {b"data": output.model_dump_json().encode()}))

    @staticmethod
    def _is_newer(entry_id: str, last_seen_id: str) -> bool:
        return FakeRawRedis._split_id(entry_id) > FakeRawRedis._split_id(last_seen_id)

    @staticmethod
    def _split_id(redis_id: str) -> tuple[int, int]:
        ms, seq = redis_id.split("-", maxsplit=1)
        return int(ms), int(seq)


def make_servicer(
    redis: Any,
    *,
    chunk_persist_timeout_s: float = 5.0,
    final_result_wait_timeout_s: float = 5.0,
    final_output_poll_block_ms: int = 1,
    outbound_queue_maxsize: int = 100,
) -> tuple[AudioIngestServicer, StreamRouter, SessionProcessor]:
    """Wire a real ``RedisStreamClient`` over ``redis`` into a servicer stack."""
    client = RedisStreamClient(redis)
    router = StreamRouter()
    processor = SessionProcessor(
        redis_client=client,
        router=router,
        chunk_persist_timeout_s=chunk_persist_timeout_s,
        final_result_wait_timeout_s=final_result_wait_timeout_s,
        final_output_poll_block_ms=final_output_poll_block_ms,
    )
    servicer = AudioIngestServicer(
        session_processor=processor,
        outbound_queue_maxsize=outbound_queue_maxsize,
    )
    return servicer, router, processor


async def as_async_iter(
    chunks: list[pb2.AudioChunk],
) -> AsyncIterator[pb2.AudioChunk]:
    """Convert a list of audio chunks into an async generator."""
    for chunk in chunks:
        yield chunk


async def wait_for_session_route(router: StreamRouter, session_id: str) -> None:
    """Wait until a client stream registers a route for the given session id."""
    for _ in range(50):
        if router.is_active(session_id):
            return
        await asyncio.sleep(0)
    raise AssertionError(f"session route was not registered for {session_id}")


class QueueEventIterator:
    """Async iterator with externally controlled push/close semantics."""

    def __init__(self) -> None:
        """Initialize internal queue state."""
        self._queue: asyncio.Queue[pb2.AudioChunk | None] = asyncio.Queue()

    async def push(self, chunk: pb2.AudioChunk) -> None:
        """Push a single client chunk into the iterator."""
        await self._queue.put(chunk)

    async def close(self) -> None:
        """Signal iterator completion."""
        await self._queue.put(None)

    def __aiter__(self) -> QueueEventIterator:
        """Return self as an async iterator."""
        return self

    async def __anext__(self) -> pb2.AudioChunk:
        """Read next queued chunk or end iteration when closed."""
        chunk = await self._queue.get()
        if chunk is None:
            raise StopAsyncIteration
        return chunk


def audio_chunk(samples: list[float], session_id: str | None = None) -> pb2.AudioChunk:
    """Encode float32 samples into one AudioChunk payload."""
    return pb2.AudioChunk(
        audio=np.array(samples, dtype=np.float16).tobytes(),
        session_id=session_id or "",
    )


def empty_audio_chunk() -> pb2.AudioChunk:
    """Build an empty chunk for validation edge cases."""
    return pb2.AudioChunk(audio=b"")


async def collect_responses(
    servicer: AudioIngestServicer,
    chunks: list[pb2.AudioChunk],
    context: FakeContext,
) -> list[pb2.ServerEvent]:
    """Collect all server responses from the StreamAudio RPC."""
    return [
        response
        async for response in servicer.StreamAudio(
            as_async_iter(chunks),
            context,  # type: ignore[arg-type]
        )
    ]
