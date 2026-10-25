"""Socket.IO session orchestration: upload -> store -> stream -> aggregate.

The handler is created when a client emits an ``upload`` event with audio data
and metadata. It persists the session, archives audio to object storage,
partitions and streams it to stream-api, emits periodic status heartbeats while
waiting, then returns the aggregated transcript and closes the session.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Annotated
import asyncio
import logging
import contextlib
from dataclasses import field, dataclass

from pydantic import Field, BaseModel, ConfigDict, ValidationError, StringConstraints
import socketio

from ..domain import (
    ErrorKey,
    RestApiError,
    SessionStatus,
)

from ..pipeline import (
    StreamResult,
    StreamFailure,
    TranscriptAggregator,
    iter_audio_chunks,
)
from ..summary.summarization_service import SummarizationFailure
from stt_common.audio import calc_bytes_per_ms, vad_collector
import numpy as np

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ..db import SessionView
    from ..domain import AggregatedTranscript
    from ..context import AppContext
    from ..pipeline import StreamEvent
    from ..summary.summarization_service import SummarizationResponse

logger = logging.getLogger(__name__)

_DEADLINE_CODE = "DEADLINE_EXCEEDED"


NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


@dataclass
class _ChunkDeadline:
    """A sliding timeout that falls fast on a stall instead of waiting for one fixed deadline.

    Every outbound chunk sent, or inbound event received, pushes the deadline
    forward by ``max(chunk_duration_s * fraction, min_window_s)`` measured from
    "now", so the allowed stall window scales with the size of the most
    recent chunk rather than the total length of the recording.

    Attributes:
        bytes_per_second: Audio byte rate, used to convert a chunk's size into
            its playback duration.
        fraction: Multiplier applied to a chunk's duration to derive its
            timeout window.
        min_window_s: Minimum timeout window regardless of chunk duration.
        deadline: Monotonic timestamp at which the stream is considered
            stalled if no progress has been made.
    """

    bytes_per_second: float
    fraction: float
    min_window_s: float
    _window_s: float = field(init=False, default=0.0)
    deadline: float = field(init=False, default=float("inf"))

    def note_chunk(self, chunk: bytes) -> None:
        """Record a newly sent chunk's duration and push the deadline forward."""
        duration_s = len(chunk) / self.bytes_per_second if self.bytes_per_second > 0 else 0.0
        self._window_s = max(duration_s * self.fraction, self.min_window_s)
        self.note_progress()

    def note_progress(self) -> None:
        """Push the deadline forward using the most recently observed chunk window."""
        self.deadline = time.monotonic() + self._window_s

    def remaining_s(self) -> float:
        """Seconds left before the sliding deadline trips (may be negative)."""
        return self.deadline - time.monotonic()


class ClientMetadataMessage(BaseModel):
    """Upload metadata envelope validated before session creation."""

    model_config = ConfigDict(extra="forbid")
    participant_ids: Annotated[list[NonEmptyStr], Field(min_length=1)]
    meeting_type: NonEmptyStr
    channels: int = Field(ge=1)
    sample_width: int = Field(ge=1)
    sample_rate: int = Field(ge=1)


class StreamSessionHandler:
    """Drives one upload-and-transcribe Socket.IO session to completion."""

    def __init__(
        self,
        sio: socketio.AsyncServer,
        sid: str,
        context: AppContext,
        *,
        session_id: str,
        user_id: str,
    ) -> None:
        self._sio = sio
        self._sid = sid
        self._ctx = context
        self._session_id = session_id
        self._user_id = user_id
        self._session: SessionView | None = None
        self._closed = False

    async def on_upload(self, *, metadata: dict[str, object], audio: bytes) -> None:
        """Handle the upload event: validate metadata, save session, process audio."""
        # --- validate metadata ---
        try:
            message = ClientMetadataMessage.model_validate(metadata)
        except ValidationError:
            await self._emit_error(ErrorKey.INVALID_METADATA)
            return

        # --- check audio size ---
        if len(audio) > self._ctx.config.max_upload_bytes:
            await self._emit_error(ErrorKey.UPLOAD_TOO_LARGE)
            return

        # --- fetch prompt before any expensive processing ---
        try:
            system_prompt = await self._ctx.prompt_repository.get(
                user_id=self._user_id,
                meeting_type=message.meeting_type,
            )
        except RestApiError as exc:
            await self._emit_error(exc.key)
            return

        # --- persist session ---
        try:
            self._session = await self._ctx.store.create_session(
                session_id=self._session_id,
                participant_ids=message.participant_ids,
                meeting_type=message.meeting_type,
                status=SessionStatus.CREATED,
            )
        except RestApiError as exc:
            await self._emit_error(exc.key)
            return

        await self._sio.emit("accepted", {"session_id": self._session_id}, to=self._sid)

        # --- process audio ---
        try:
            #
            bytes_per_ten_ms = calc_bytes_per_ms(
                sample_rate=message.sample_rate,
                channels=message.channels,
                sample_width=message.sample_width,
            )
            vad_result = vad_collector(
                audio,
                int(bytes_per_ten_ms),
                sample_rate=message.sample_rate
            )

            # Find where runs of 1s start and end
            starts = np.where((vad_result == True) & (np.r_[False, vad_result[:-1]] == False))[0]
            ends   = np.where((vad_result == True) & (np.r_[vad_result[1:], False] == False))[0]

            sub_audios = [audio[start:end + 1] for start, end in zip(starts, ends)]
            tasks = []
            for sub_audio in sub_audios:
                tasks.append(self._process(
                    sub_audio,
                    channels=message.channels,
                    sample_width=message.sample_width,
                    sample_rate=message.sample_rate,
                ))

            transcripts = await asyncio.gather(*tasks)
            transcript = AggregatedTranscript(text=" ".join([t.text for t in transcripts if t is not None]))

            deliver_transcript_task = asyncio.create_task(self._deliver_transcript(transcript))
            summarize_task = asyncio.create_task(self._summarize(transcript, system_prompt=system_prompt))
            _, summary = await asyncio.gather(deliver_transcript_task, summarize_task)

            await self._deliver_summary(summary)
            await self._close_session()
        except RestApiError as exc:
            await self._abort(exc)
        except Exception:
            logger.exception(
                "unexpected stream handler failure",
                extra={"session_id": self._session_id},
            )
            await self._abort(RestApiError(key=ErrorKey.INTERNAL))

    async def on_disconnect(self) -> None:
        """Handle client disconnection mid-session."""
        if self._session is not None:
            logger.info(
                "client disconnected during streaming",
                extra={"session_id": self._session_id},
            )
            await self._safe_mark_failed()

    # --- lifecycle steps ----------------------------------------------------

    async def _process(
        self,
        audio: bytes,
        *,
        channels: int,
        sample_width: int,
        sample_rate: int,
    ) -> AggregatedTranscript:
        """Store audio, stream it upstream, and aggregate the transcript."""
        config = self._ctx.config
        session_id = self._session_id

        await self._ctx.store.update_status(session_id, SessionStatus.STREAMING)
        await self._ctx.storage.upload_audio(session_id=session_id, data=audio)
        await self._emit_status(SessionStatus.STREAMING, 0.0)

        aggregator = TranscriptAggregator()
        client = self._ctx.stream_client_factory()
        await self._ctx.store.update_status(session_id, SessionStatus.PROCESSING)

        started_at = time.monotonic()
        stream_done = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(stream_done, started_at))

        deadline = _ChunkDeadline(
            bytes_per_second=sample_rate * sample_width * channels,
            fraction=config.chunk_timeout_fraction,
            min_window_s=config.chunk_timeout_min_s,
        )

        async def consume() -> None:
            # TODO: use inference_adapter.audio.calc_bytes_per_ms (will be moved to stt_common).
            chunk_size_bytes = int(self._ctx.config.chunk_duration_seconds * sample_rate * sample_width * channels)

            async for event in client.stream_audio(
                self._chunk_source(audio, chunk_size_bytes, deadline),
                channels=channels,
                sample_width=sample_width,
                sample_rate=sample_rate,
            ):
                deadline.note_progress()
                await self._handle_event(event, aggregator)

        consume_task = asyncio.create_task(consume())

        audio_duration_s = len(audio) / deadline.bytes_per_second if deadline.bytes_per_second > 0 else 0.0
        overall_timeout_s = max(
            audio_duration_s * config.upload_overall_timeout_fraction,
            config.final_result_wait_timeout_s,
        )
        overall_deadline = started_at + overall_timeout_s

        try:
            await self._await_with_chunk_timeout(consume_task, deadline, overall_deadline=overall_deadline)
        except TimeoutError:
            logger.warning(
                "timed out waiting for transcript; returning best-effort result",
                extra={"session_id": session_id},
            )
        finally:
            stream_done.set()
            await heartbeat

        return aggregator.build()

    async def _await_with_chunk_timeout(
        self,
        consume_task: asyncio.Task[None],
        deadline: _ChunkDeadline,
        *,
        overall_deadline: float,
    ) -> None:

        while True:
            remaining = min(deadline.remaining_s(), overall_deadline - time.monotonic())
            if remaining <= 0:
                consume_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await consume_task
                raise TimeoutError("per-chunk or overall stream timeout exceeded")
            done, _ = await asyncio.wait({consume_task}, timeout=remaining)
            if consume_task in done:
                await consume_task
                return

    async def _summarize(
        self,
        transcript: AggregatedTranscript,
        *,
        system_prompt: str,
    ) -> SummarizationResponse | SummarizationFailure:
        """Summarize the transcript; returns SummarizationFailure on error instead of raising."""
        try:
            return await self._ctx.summarization_service.summarize(
                transcript,
                system_prompt=system_prompt,
            )
        except Exception as exc:
            logger.warning(
                "summarization failed; continuing without summary",
                extra={"session_id": self._session_id},
                exc_info=True,
            )
            return SummarizationFailure(reason=str(exc))

    async def _deliver_transcript(self, transcript: AggregatedTranscript) -> None:
        """Persist the transcript and emit the transcript event."""
        # TODO: rename the method of close_session cause its confusing
        await self._ctx.store.close_session(
            self._session_id,
            text=transcript.text,
        )
        self._closed = True
        await self._sio.emit(
            "transcript",
            {"text": transcript.text},
            to=self._sid,
        )

    async def _deliver_summary(self, result: SummarizationResponse | SummarizationFailure) -> None:
        """Emit the summary event; includes an error field if summarization failed."""
        if isinstance(result, SummarizationFailure):
            payload: dict[str, object] = {"error": result.reason}
        else:
            payload = dict(result.data)
        await self._sio.emit("summary", payload, to=self._sid)

    async def _close_session(self) -> None:
        """Emit the closed event and disconnect the client."""
        await self._sio.emit(
            "closed",
            {"session_id": self._session_id, "status": str(SessionStatus.CLOSED)},
            to=self._sid,
        )
        await self._sio.disconnect(self._sid)

    # --- helpers ------------------------------------------------------------

    async def _handle_event(self, event: StreamEvent, aggregator: TranscriptAggregator) -> None:
        """Apply one upstream event to the aggregation state."""
        if isinstance(event, StreamResult):
            aggregator.add_result(
                text=event.text,
                is_final=event.is_final,
            )
        elif isinstance(event, StreamFailure):
            if event.code == _DEADLINE_CODE:
                logger.info(
                    "stream-api reported final-result timeout; best-effort transcript",
                    extra={"session_id": self._session_id},
                )

            else:
                raise RestApiError(key=ErrorKey.UPSTREAM_STREAM_FAILURE)

    async def _heartbeat(self, stream_done: asyncio.Event, started_at: float) -> None:
        """Emit a status event every ``status_update_interval_s`` until done."""
        interval = self._ctx.config.status_update_interval_s
        while not stream_done.is_set():
            try:
                await asyncio.wait_for(stream_done.wait(), timeout=interval)
            except TimeoutError:
                try:
                    await self._emit_status(SessionStatus.PROCESSING, time.monotonic() - started_at)
                except Exception:
                    logger.debug("status heartbeat send failed; stopping heartbeat")
                    return

    async def _chunk_source(self, audio: bytes, chunk_size: int, deadline: _ChunkDeadline) -> AsyncIterator[bytes]:
        """Yield the buffered audio as fixed-size chunks for the gRPC stream."""
        for chunk in iter_audio_chunks(audio, chunk_size):
            deadline.note_chunk(chunk)
            yield chunk

    async def _emit_error(self, key: ErrorKey) -> None:
        """Emit an error event to the client."""
        try:
            message = RestApiError(key=key).message or ""
            await self._sio.emit("error", {"code": str(key), "message": message}, to=self._sid)
        except Exception:
            logger.debug(
                "failed to emit error to client",
                extra={"session_id": self._session_id, "error_key": str(key)},
                exc_info=True,
            )

    async def _emit_status(self, state: SessionStatus, elapsed_s: float) -> None:
        """Emit a status heartbeat event."""
        await self._sio.emit(
            "status",
            {"state": str(state), "elapsed_s": round(elapsed_s, 3)},
            to=self._sid,
        )

    async def _abort(self, error: RestApiError) -> None:
        """Mark the session failed, emit an error, and disconnect."""
        await self._safe_mark_failed()
        try:
            await self._sio.emit(
                "error",
                {"code": str(error.key), "message": error.message or "error"},
                to=self._sid,
            )
            await self._sio.disconnect(self._sid)
        except Exception:
            logger.debug(
                "failed to emit error/disconnect during abort",
                extra={"session_id": self._session_id, "error_key": str(error.key)},
                exc_info=True,
            )

    async def _safe_mark_failed(self) -> None:
        """Best-effort transition to FAILED if the session is not already closed."""
        if self._closed or self._session is None:
            return
        try:
            await self._ctx.store.fail_session(self._session_id)
        except Exception:
            logger.debug(
                "failed to mark session as failed",
                extra={"session_id": self._session_id},
                exc_info=True,
            )
