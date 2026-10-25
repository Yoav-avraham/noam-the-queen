"""Standalone helpers for session processor flow."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from stt_common.contracts import ServiceOutput, WindowPayload, ReadyAudioWindowContent
from stt_common.redis_stream_client import RedisStreamClient

from ..proto import audio_ingest_pb2 as pb2

logger = logging.getLogger(__name__)


def build_ready_audio_output(
    *,
    session_id: str,
    sequence_number: int,
    is_final: bool,
    audio: bytes,
    channels: int,
    sample_width: int,
    sample_rate: int,
) -> ServiceOutput:
    """Build the Redis envelope for one ready-audio message."""
    return ServiceOutput(
        session_id=session_id,
        sequence_id=sequence_number,
        is_final=is_final,
        window_payload=WindowPayload(
            content=ReadyAudioWindowContent(
                raw_bytes=audio,
                channels=channels,
                sample_width=sample_width,
                sample_rate=sample_rate,
            ).model_dump(mode="json"),
        ),
    )


def to_result_event(
    *,
    session_id: str,
    redis_id: str,
    fields: Mapping[bytes, bytes],
) -> pb2.TranscriptionResultEvent | None:
    """Map one final_output Redis entry into a transcription result event."""
    data_field = fields.get(RedisStreamClient.DATA_FIELD)

    if data_field is None:
        logger.warning(
            "dropping final_output message without data field",
            extra={"session_id": session_id, "redis_id": redis_id},
        )
        return None

    try:
        output = ServiceOutput.model_validate_json(data_field)
    except Exception:
        logger.exception(
            "failed parsing final_output service envelope",
            extra={"session_id": session_id, "redis_id": redis_id},
        )
        return None

    if output.session_id != session_id:
        logger.warning(
            "dropping final_output message with mismatched session",
            extra={
                "expected_session_id": session_id,
                "received_session_id": output.session_id,
                "redis_id": redis_id,
            },
        )
        return None

    content = output.window_payload.content
    text = content.get("text")
    partial_text = text if isinstance(text, str) else ""

    return pb2.TranscriptionResultEvent(
        session_id=output.session_id,
        partial_text=partial_text,
        is_final=output.is_final,
    )
