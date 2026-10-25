"""Shared domain contracts for the rest API service."""

from __future__ import annotations

from enum import StrEnum
from dataclasses import dataclass


class SessionStatus(StrEnum):
    """Lifecycle states for a transcription session.

    State machine:
        CREATED -> STREAMING -> PROCESSING -> CLOSED
        (any active state) -> FAILED
    """

    CREATED = "created"
    STREAMING = "streaming"
    PROCESSING = "processing"
    CLOSED = "closed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """One transcription fragment routed back from the pipeline."""

    text: str
    is_final: bool
    sequence: int


@dataclass(frozen=True, slots=True)
class AggregatedTranscript:
    """Full transcript assembled from ordered partial segments."""

    text: str
