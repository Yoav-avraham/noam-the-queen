"""Per-session lifecycle owner for one live client audio stream."""

from __future__ import annotations

import uuid
import asyncio
import logging
from collections.abc import AsyncIterator

from stt_common.contracts import (
    StreamName,
)
from stt_common.redis_stream_client import RedisStreamClient
from stream_api.ingest.session_processor_helpers import to_result_event, build_ready_audio_output

from .state import StreamState
from ..proto import audio_ingest_pb2 as pb2
from ..types import ServerEventQueue
from ..errors import ErrorKey, get_error_definition
from .stream_router import StreamRouter

logger = logging.getLogger(__name__)


class SessionProcessor:
    """Processes one client audio stream and persists accepted chunks.

    Owns the per-session stream lifecycle: consuming inbound ``AudioChunk``s,
    sequencing them, writing ready-audio envelopes to Redis, consuming the
    session's ``final_output`` stream, waiting for the final result, mapping
    errors, and closing the outbound queue.
    """

    # Final-output polling: initial cursor, batch size, and error backoff.
    INITIAL_LAST_SEEN_ID = "0-0"
    FINAL_OUTPUT_READ_COUNT = 10
    FINAL_OUTPUT_ERROR_BACKOFF_S = 0.1

    def __init__(
        self,
        *,
        redis_client: RedisStreamClient,
        router: StreamRouter,
        chunk_persist_timeout_s: float,
        final_result_wait_timeout_s: float,
        final_output_poll_block_ms: int,
    ) -> None:
        if chunk_persist_timeout_s <= 0:
            raise ValueError(f"chunk_persist_timeout_s must be > 0, got: {chunk_persist_timeout_s}")

        if final_result_wait_timeout_s <= 0:
            raise ValueError(f"final_result_wait_timeout_s must be > 0, got: {final_result_wait_timeout_s}")

        if final_output_poll_block_ms <= 0:
            raise ValueError(f"final_output_poll_block_ms must be > 0, got: {final_output_poll_block_ms}")

        self._router = router
        self._redis = redis_client
        self._chunk_persist_timeout_s = chunk_persist_timeout_s
        self._final_result_wait_timeout_s = final_result_wait_timeout_s
        self._final_output_poll_block_ms = final_output_poll_block_ms

    async def consume_client_stream(
        self,
        *,
        request_iterator: AsyncIterator[pb2.AudioChunk],
        outbound_queue: ServerEventQueue,
    ) -> None:
        """Consume audio chunks and persist each accepted chunk to Redis."""
        state: StreamState | None = None
        queue_closed = False

        try:
            async for chunk in request_iterator:
                if not chunk.audio:
                    logger.warning("ignoring empty audio chunk")
                    continue

                if state is None:
                    state = await self._handle_first_chunk(
                        chunk=chunk,
                        outbound_queue=outbound_queue,
                    )

                    if state is None:
                        queue_closed = True
                        return

                    continue

                if chunk.session_id and chunk.session_id != state.session_id:
                    logger.warning(
                        "ignoring audio chunk with mismatched session_id",
                        extra={
                            "expected_session_id": state.session_id,
                            "received_session_id": chunk.session_id,
                        },
                    )
                    continue

                if not await self._handle_audio_chunk(
                    state=state,
                    chunk=chunk,
                    outbound_queue=outbound_queue,
                ):
                    return

            if state is not None:
                if not await self._flush_final_chunk(state, outbound_queue):
                    return
                logger.info(
                    "client stream half-closed, persisted final chunk",
                    extra={"session_id": state.session_id},
                )

                completion_received = await self._router.wait_for_completion(
                    state.session_id,
                    self._final_result_wait_timeout_s,
                )

                if not completion_received:
                    await self._enqueue_mapped_error(outbound_queue, ErrorKey.FINAL_RESULT_TIMEOUT)

                await self._close_session_stream(state.session_id, outbound_queue)
                queue_closed = True
            else:
                logger.info("client stream closed without sending audio")
                await outbound_queue.put(None)
                queue_closed = True

        except asyncio.CancelledError:
            logger.info("client stream cancelled")

        except Exception as exc:
            error_def = get_error_definition(ErrorKey.UNEXPECTED_STREAM_FAILURE)
            logger.exception(
                "unexpected error in stream consumption",
                extra={
                    "session_id": state.session_id if state is not None else None,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "error_key": ErrorKey.UNEXPECTED_STREAM_FAILURE.value,
                    "stream_phase": error_def.context,
                },
            )
            await self._enqueue_mapped_error(
                outbound_queue,
                ErrorKey.UNEXPECTED_STREAM_FAILURE,
            )

        finally:
            if not queue_closed:
                if state is not None:
                    await self._close_session_stream(state.session_id, outbound_queue)
                else:
                    await outbound_queue.put(None)

    async def _handle_first_chunk(
        self,
        *,
        chunk: pb2.AudioChunk,
        outbound_queue: ServerEventQueue,
    ) -> StreamState | None:
        """Create session state, register route, persist first chunk, and send ACK."""
        session_id = chunk.session_id or str(uuid.uuid4())
        state = StreamState(session_id=session_id)

        is_registered = await self._router.register(session_id, outbound_queue)

        if not is_registered:
            error_def = get_error_definition(ErrorKey.SESSION_REGISTRATION_FAILED)
            logger.error(
                "failed to register session route (session already active?)",
                extra={
                    "session_id": session_id,
                    "error_key": ErrorKey.SESSION_REGISTRATION_FAILED.value,
                    "stream_phase": error_def.context,
                },
            )
            await self._enqueue_mapped_error(outbound_queue, ErrorKey.SESSION_REGISTRATION_FAILED)
            await self._close_session_stream(session_id, outbound_queue)

            return None

        final_output_task = asyncio.create_task(self._consume_final_output_session(session_id))
        self._router.set_final_output_task(session_id, final_output_task)

        if not await self._announce_session(state.session_id, outbound_queue):
            await self._close_session_stream(session_id, outbound_queue)

            return None

        # Buffer the first chunk; it is persisted once the next chunk arrives
        # (is_final=False) or at half-close (is_final=True). This lets stream-api
        # mark the actual last chunk as final instead of writing a synthetic marker.
        state.pending_chunk = chunk

        await outbound_queue.put(
            pb2.ServerEvent(
                ack=pb2.StreamAck(
                    session_id=session_id,
                    status="ok",
                )
            )
        )

        logger.info(
            (
                "ingest stream opened and first chunk accepted ",
                f"session_id: {session_id} "
            ),
            extra={"session_id": session_id},
        )

        return state

    async def _handle_audio_chunk(
        self,
        *,
        state: StreamState,
        chunk: pb2.AudioChunk,
        outbound_queue: ServerEventQueue,
    ) -> bool:
        """Persist the previously buffered chunk, then buffer this one."""
        pending = state.pending_chunk

        if pending is not None:
            persisted = await self._write_chunk_to_redis(
                session_id=state.session_id,
                sequence_number=state.next_sequence(),
                is_final=False,
                audio=pending.audio,
                channels=pending.channels,
                sample_width=pending.sample_width,
                sample_rate=pending.sample_rate,
                outbound_queue=outbound_queue,
            )

            if not persisted:
                return False

        state.pending_chunk = chunk
        return True

    async def _flush_final_chunk(
        self,
        state: StreamState,
        outbound_queue: ServerEventQueue,
    ) -> bool:
        """Persist the buffered last chunk for the session with is_final=True."""
        pending = state.pending_chunk

        if pending is None:
            logger.info(
                "no pending chunk to flush for session",
                extra={"session_id": state.session_id},
            )
            return True

        logger.info(
            "flushing final chunk for session",
            extra={"session_id": state.session_id},
        )

        return await self._write_chunk_to_redis(
            session_id=state.session_id,
            sequence_number=state.next_sequence(),
            is_final=True,
            audio=pending.audio,
            channels=pending.channels,
            sample_width=pending.sample_width,
            sample_rate=pending.sample_rate,
            outbound_queue=outbound_queue,
        )

    async def _announce_session(self, session_id: str, outbound_queue: ServerEventQueue) -> bool:
        """Announce a new active session in Redis."""
        try:
            await asyncio.wait_for(
                self._redis.announce_session(session_id),
                timeout=self._chunk_persist_timeout_s,
            )

        except TimeoutError:
            error_def = get_error_definition(ErrorKey.SESSION_REGISTRATION_FAILED)
            logger.exception(
                "session announcement timeout",
                extra={
                    "session_id": session_id,
                    "error_key": ErrorKey.SESSION_REGISTRATION_FAILED.value,
                    "stream_phase": error_def.context,
                },
            )
            await self._enqueue_mapped_error(outbound_queue, ErrorKey.SESSION_REGISTRATION_FAILED)

            return False

        except Exception:
            error_def = get_error_definition(ErrorKey.SESSION_REGISTRATION_FAILED)
            logger.exception(
                "failed announcing session to redis",
                extra={
                    "session_id": session_id,
                    "error_key": ErrorKey.SESSION_REGISTRATION_FAILED.value,
                    "stream_phase": error_def.context,
                },
            )
            await self._enqueue_mapped_error(outbound_queue, ErrorKey.SESSION_REGISTRATION_FAILED)

            return False

        return True

    async def _write_chunk_to_redis(
        self,
        *,
        session_id: str,
        sequence_number: int,
        is_final: bool,
        audio: bytes,
        channels: int,
        sample_width: int,
        sample_rate: int,
        outbound_queue: ServerEventQueue,
    ) -> bool:
        """Write one ready-audio chunk to Redis (silent, no ACK)."""
        output = build_ready_audio_output(
            session_id=session_id,
            sequence_number=sequence_number,
            is_final=is_final,
            audio=audio,
            channels=channels,
            sample_width=sample_width,
            sample_rate=sample_rate,
        )
        try:
            entry_id = await asyncio.wait_for(
                self._redis.append_output(StreamName.READY_AUDIO, output),
                timeout=self._chunk_persist_timeout_s,
            )

        except TimeoutError:
            error_def = get_error_definition(ErrorKey.CHUNK_PERSIST_TIMEOUT)
            logger.exception(
                "chunk persistence timeout",
                extra={
                    "session_id": session_id,
                    "sequence_number": sequence_number,
                    "is_final": is_final,
                    "error_key": ErrorKey.CHUNK_PERSIST_TIMEOUT.value,
                    "stream_phase": error_def.context,
                },
            )
            await self._enqueue_mapped_error(outbound_queue, ErrorKey.CHUNK_PERSIST_TIMEOUT)

            return False

        except Exception:
            error_def = get_error_definition(ErrorKey.CHUNK_PERSIST_FAILED)
            logger.exception(
                "failed to persist chunk to redis",
                extra={
                    "session_id": session_id,
                    "sequence_number": sequence_number,
                    "is_final": is_final,
                    "error_key": ErrorKey.CHUNK_PERSIST_FAILED.value,
                    "stream_phase": error_def.context,
                },
            )
            await self._enqueue_mapped_error(outbound_queue, ErrorKey.CHUNK_PERSIST_FAILED)

            return False

        logger.debug(
            "chunk persisted to redis",
            extra={
                "session_id": session_id,
                "sequence_number": sequence_number,
                "is_final": is_final,
                "audio_bytes": len(audio),
                "entry_id": entry_id,
            },
        )

        return True

    async def _consume_final_output_session(self, session_id: str) -> None:
        """Read and route final_output events for one active session route."""
        stream_key = self._redis.stream_key(StreamName.FINAL_OUTPUT, session_id)
        last_seen_id = self.INITIAL_LAST_SEEN_ID

        while True:
            try:
                messages = await self._redis.xread(
                    streams={stream_key: last_seen_id},
                    count=self.FINAL_OUTPUT_READ_COUNT,
                    block=self._final_output_poll_block_ms,
                )

                if not messages:
                    continue

                for _stream, entries in messages:
                    for entry_id, fields in entries:
                        redis_id = self._redis.to_str(entry_id)
                        last_seen_id = redis_id
                        result = to_result_event(
                            session_id=session_id,
                            redis_id=redis_id,
                            fields=fields,
                        )
                        if result is None:
                            continue

                        delivered = await self._router.route_result_event(result)

                        if delivered and result.is_final:
                            return

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception(
                    "failed reading final_output stream",
                    extra={"session_id": session_id, "stream_key": stream_key},
                )
                await asyncio.sleep(self.FINAL_OUTPUT_ERROR_BACKOFF_S)

    async def _close_session_stream(
        self,
        session_id: str,
        outbound_queue: ServerEventQueue,
    ) -> None:
        """Cancel final-output consumption, unregister the route, and close the queue."""
        await self._router.cancel_final_output_task(session_id)
        await self._router.unregister(session_id, outbound_queue)
        await outbound_queue.put(None)

    async def _enqueue_mapped_error(
        self,
        outbound_queue: ServerEventQueue,
        error_key: ErrorKey,
    ) -> None:
        """Emit one client-facing error event from canonical runtime mapping."""
        error_def = get_error_definition(error_key)
        message = error_def.message or ""
        await outbound_queue.put(pb2.ServerEvent(error=pb2.StreamError(code=error_def.status.name, message=message)))
