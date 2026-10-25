from __future__ import annotations
from dataclasses import dataclass

type InterleavedTranscriptItem = tuple[float, int, str]


@dataclass(frozen=True, slots=True)
class MergedTranscript:
    """Result of merging one window into publish-ready text.

    ``last_speaker_id`` carries the speaker context needed to evaluate
    continuation suppression on the next window for the same session.
    """
    transcript_object: list[dict[str, str]]
    finalized_text: str
    last_speaker_id: str | None = None
