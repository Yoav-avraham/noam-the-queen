from __future__ import annotations

from dataclasses import dataclass

from ..proto import audio_ingest_pb2 as pb2


@dataclass(slots=True)
class StreamState:
    """Tracks state for one active audio ingestion session."""

    session_id: str
    _sequence_counter: int = 1
    pending_chunk: pb2.AudioChunk | None = None

    def next_sequence(self) -> int:
        """Return the next monotonic sequence number for this session."""
        sequence_number = self._sequence_counter
        self._sequence_counter += 1
        return sequence_number
