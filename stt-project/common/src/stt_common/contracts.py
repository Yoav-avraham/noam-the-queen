from __future__ import annotations

from enum import StrEnum
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict

ACTIVE_STREAMS_KEY = "active_streams"


# TODO(types-alignment): each service must produce/consume ServiceOutput using
# these names. Align the producers/consumers in:
#   - stream-api   -> StreamName.READY_AUDIO
#   - inference-adapter    -> StreamName.TRITON_OUTPUT
#   - synchronizer -> StreamName.FINAL_OUTPUT
class StreamName(StrEnum):
    READY_AUDIO = "ready_audio"
    TRITON_OUTPUT = "triton_output"
    FINAL_OUTPUT = "final_output"

    def next(self) -> StreamName:
        """Return the next stream in the circular pipeline order.

        Each service reads from one stream and pushes to the next; the order
        wraps around so the last stream feeds back to the first.
        """
        members = list(type(self))
        return members[(members.index(self) + 1) % len(members)]


def session_stream_key(stream_name: StreamName | str, session_id: str) -> str:
    """Build one per-session stream key in ``{stream_name}:{session_id}`` form."""
    resolved_stream = stream_name.value if isinstance(stream_name, StreamName) else stream_name
    return f"{resolved_stream}:{session_id}"


class TritonOutputSegment(TypedDict):
    """One timed segment emitted on the ``TRITON_OUTPUT`` stream."""

    start_timestamp: float
    end_timestamp: float
    value: str


class ReadyAudioWindowContent(BaseModel):
    """``WindowPayload.content`` contract for ``StreamName.READY_AUDIO``."""

    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    raw_bytes: bytes
    channels: int
    sample_width: int
    sample_rate: int


class TritonOutputWindowContent(TypedDict, total=False):
    """``WindowPayload.content`` contract for ``StreamName.TRITON_OUTPUT``."""

    words: list[TritonOutputSegment]
    speakers: list[TritonOutputSegment]


class FinalOutputWindowContent(TypedDict):
    """``WindowPayload.content`` contract for ``StreamName.FINAL_OUTPUT``."""

    text: str


class WindowPayload(BaseModel):
    """Container for one model-output window payload.

    Only ``content`` varies between services.
    """

    content: dict[str, Any]
    locale: str | None = None


class ServiceOutput(BaseModel):
    """Generic envelope exchanged between services over Redis streams.

    Replaces the per-service ReadyAudio/TritonOutput/FinalOutput models: the
    structure is identical across services and only ``window_payload.content``
    differs (hence its ``dict[str, Any]`` type).
    """

    session_id: str
    sequence_id: int
    is_final: bool
    window_payload: WindowPayload
