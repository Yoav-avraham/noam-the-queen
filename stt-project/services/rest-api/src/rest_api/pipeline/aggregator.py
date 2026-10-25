"""Aggregate streamed partial transcription results into a full transcript.

stream-api routes ``ConsumerResultEvent`` partials back to the client. Each
partial carries ``partial_text`` and an ``is_final`` flag. This aggregator
records every partial (in arrival order) and assembles a best-effort complete
transcript:

* If any ``is_final`` partials were received, the transcript is the ordered
  concatenation of their text (the confirmed utterances).
* Otherwise it falls back to the latest non-empty partial text.

Ordering is by arrival sequence so out-of-order delivery still produces a
stable transcript.
"""

from __future__ import annotations

import json
from json import JSONDecodeError

from ..domain import TranscriptSegment, AggregatedTranscript

SENTENCE_ENDS = [".", '?', "!"]


class TranscriptAggregator:
    """Collects partial transcription results and builds a transcript."""

    def __init__(self) -> None:
        self._segments: list[TranscriptSegment] = []

    def _calculate_overflow(self, sentence: str, words: list[str]) -> tuple[str, str]:
        overflow = ""

        if words[-1][-1] not in SENTENCE_ENDS:
            if len(words) >= 2 and words[-2][-1] in SENTENCE_ENDS:
                overflow = words[-1]
                sentence = " ".join(words[:-1])
            elif len(words) >= 3 and words[-3][-1] in SENTENCE_ENDS:
                overflow = " ".join(words[-2:])
                sentence = " ".join(words[:-2])

        return overflow, sentence

    def _correct_transcript(self, text: str | list[dict[str, object]]) -> str:
        if not isinstance(text, str):
            json_transcript = text
        else:
            stripped = text.strip()
            if not stripped:
                return ""
            try:
                json_transcript = json.loads(text)
            except JSONDecodeError:
                return text
            if not isinstance(json_transcript, list):
                return text

        corrected_text = ""
        previous_segment_speaker = None
        overflow = ""

        for segment in json_transcript:
            speaker = segment["speaker"]
            sentence = (overflow + " " + str(segment["sentence"])).strip()

            words = sentence.split()
            if not words:
                continue

            overflow, corrected_sentence = self._calculate_overflow(sentence, words)

            if speaker == previous_segment_speaker:
                corrected_text += f" {corrected_sentence}"
            else:
                corrected_text += f"\n דובר {speaker}: {corrected_sentence}"

            previous_segment_speaker = speaker

        if overflow:
            corrected_text += f" {overflow}"

        return corrected_text.strip()

    # def _debug_json(self, text):
    #     json_transcript = json.loads(text) if isinstance(text, str) else text

    #     corrected_text = ""
    #     previous_segment_speaker = None
    #     overflow = ""

    #     for segment in json_transcript:
    #         speaker = segment['speaker']
    #         sentence = (overflow + " " + segment['sentence']).strip()
    #         overflow = ""

    #         words = sentence.split()
    #         if not words:
    #             continue
    #         if speaker == previous_segment_speaker:
    #             corrected_text += f" {sentence}"
    #         else:
    #             corrected_text += f"\n דובר {speaker}: {sentence}"

    #         previous_segment_speaker = speaker

    #     if overflow:
    #         corrected_text += f" {overflow}"

    #     print("-----------------------")
    #     print(corrected_text.strip())
    #     print("-----------------------")

    def add_result(
        self,
        *,
        text: str,
        is_final: bool,
    ) -> TranscriptSegment:
        """Record one partial result and return the stored segment."""
        corrected_text = self._correct_transcript(text)
        segment = TranscriptSegment(
            text=corrected_text,
            is_final=is_final,
            sequence=len(self._segments),
        )
        self._segments.append(segment)
        return segment

    @property
    def has_final(self) -> bool:
        """Return True once at least one final result has been received."""
        return any(segment.is_final for segment in self._segments)

    @property
    def segments(self) -> tuple[TranscriptSegment, ...]:
        """Return all recorded segments in arrival order."""
        return tuple(self._segments)

    def build(self) -> AggregatedTranscript:
        """Assemble the aggregated transcript from recorded segments."""
        ordered = sorted(self._segments, key=lambda segment: segment.sequence)

        final_texts = [segment.text.strip() for segment in ordered if segment.is_final and segment.text.strip()]
        if final_texts:
            text = " ".join(final_texts)
        else:
            text = next(
                (segment.text.strip() for segment in reversed(ordered) if segment.text.strip()),
                "",
            )
        return AggregatedTranscript(text=text)
