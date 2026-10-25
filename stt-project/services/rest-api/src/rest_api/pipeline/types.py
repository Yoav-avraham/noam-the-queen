"""Typed event definitions for the stream-api pipeline.

These dataclasses model the server events surfaced by the gRPC client so the
rest of the service never imports protobuf types directly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StreamAck:
    """Session acknowledgement; carries the stream-api-assigned session id."""

    session_id: str
    status: str


@dataclass(frozen=True, slots=True)
class StreamResult:
    """One routed transcription partial from the pipeline."""

    session_id: str
    text: str
    is_final: bool


@dataclass(frozen=True, slots=True)
class StreamFailure:
    """In-band error event emitted by stream-api (not an RPC abort)."""

    code: str
    message: str


StreamEvent = StreamAck | StreamResult | StreamFailure
