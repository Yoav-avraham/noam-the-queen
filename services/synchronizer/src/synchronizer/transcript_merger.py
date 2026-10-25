from __future__ import annotations

import logging
from dataclasses import field, dataclass
from collections.abc import Mapping

import i18n

from stt_common.contracts import TritonOutputSegment, TritonOutputWindowContent

from .types import (
    MergedTranscript,
    InterleavedTranscriptItem,
)
from .localization import Locale, configure_i18n

logger = logging.getLogger(__name__)

# Sort ranks placing a speaker marker before a word at the same start time, so a
# word sharing a turn's start timestamp is attributed to that new speaker.
_SPEAKER_RANK = 0
_WORD_RANK = 1


@dataclass(slots=True)
class TranscriptMerger:
    """Merge a window's speaker and word arrays into localized transcript text.

    Stateful per session: the last speaker id is retained so a speaker who
    continues at the start of the next window is rendered without a repeated
    label. A single window ``content`` message carries two timestamped arrays —
    ``speakers`` (diarized turn starts) and ``words`` — which are interleaved by
    start time to reconstruct who said what; word data is produced upstream and
    not recomputed.
    """

    _last_speaker_id: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Ensure the i18n catalogs/fallback are loaded before any label lookup,
        # so the merger is usable without external setup in production or tests.
        configure_i18n()

    def merge_window(
        self,
        *,
        session_id: str,
        content: TritonOutputWindowContent,
        locale: str | None,
        is_final: bool,
    ) -> MergedTranscript:
        """Merge one window's speaker/word arrays into publish-ready text.

        Raises :class:`TypeError`/:class:`KeyError`/:class:`ValueError` on
        malformed content so the synchronizer runtime can fail the message
        explicitly.
        """
        label = i18n.t("speaker.label", locale=Locale.from_tag(locale))
        ordered = self._interleave_by_start(self._validate_content(content))

        previous_speaker_id = self._last_speaker_id.get(session_id)
        current_speaker_id = previous_speaker_id
        window_last_speaker_id: str | None = None
        speaker_count = 0
        listdict: list[dict[str, str]] = []
        parts: list[str] = []

        for _start, rank, value in ordered:
            if rank == _SPEAKER_RANK:
                speaker_count += 1
                window_last_speaker_id = value

                # A new speaker opens a labeled turn on its own line
                if value != current_speaker_id:
                    # Trim trailing space from the last word before starting a new speaker line
                    if parts and not parts[-1].endswith(": "):
                        parts[-1] = parts[-1].rstrip()
                    parts.append(f"\n{label} {value}: ")
                    listdict.append({"speaker": value, "sentence": ""})
                    current_speaker_id = value
                elif not listdict:
                    # Same speaker as previous window, but we still need an
                    # entry in listdict to hold this window's words.
                    listdict.append({"speaker": value, "sentence": ""})
            else:
                # Word continuing the open turn.
                # Safety check: if no speaker has been identified yet in this
                # window or previously, create a default entry.
                if not listdict:
                    speaker_id = current_speaker_id or "Unknown"
                    listdict.append({"speaker": speaker_id, "sentence": ""})

                listdict[-1]["sentence"] += f"{value} "
                parts.append(f"{value} ")

        for item in listdict:
            item["sentence"] = item["sentence"].rstrip()
        finalized_text = "".join(parts).rstrip()
        last_speaker_id = window_last_speaker_id if window_last_speaker_id is not None else previous_speaker_id

        if is_final:
            self._last_speaker_id.pop(session_id, None)
        elif window_last_speaker_id is not None:
            self._last_speaker_id[session_id] = window_last_speaker_id

        logger.debug(
            "merged transcript window",
            extra={
                "session_id": session_id,
                "speaker_count": speaker_count,
                "is_final": is_final,
            },
        )

        return MergedTranscript(
            transcript_object=listdict,
            finalized_text=finalized_text,
            last_speaker_id=last_speaker_id,
        )

    @staticmethod
    def _interleave_by_start(content: TritonOutputWindowContent) -> list[InterleavedTranscriptItem]:
        """Interleave the window's ``speakers`` and ``words`` arrays by start time.

        Both arrays travel in the same window ``content`` message. Each entry
        is an object carrying start/end timestamps plus a string value. The
        combined list is sorted by start, with speaker markers ordered before
        words sharing a timestamp; each array is assumed individually
        pre-sorted.
        """
        raw_speakers = content.get("speakers", [])
        raw_words = content.get("words", [])
        items: list[InterleavedTranscriptItem] = []
        for raw_speaker in raw_speakers:
            items.append(TranscriptMerger._segment_to_item(raw_speaker, _SPEAKER_RANK))
        for raw_word in raw_words:
            items.append(TranscriptMerger._segment_to_item(raw_word, _WORD_RANK))

        items.sort(key=lambda item: (item[0], item[1]))
        return items

    @staticmethod
    def _validate_content(content: TritonOutputWindowContent) -> TritonOutputWindowContent:
        raw_speakers = content.get("speakers", [])
        raw_words = content.get("words", [])
        if not isinstance(raw_speakers, list):
            raise TypeError("window content 'speakers' must be a list")
        if not isinstance(raw_words, list):
            raise TypeError("window content 'words' must be a list")

        return TritonOutputWindowContent(
            speakers=[TranscriptMerger._validate_segment(raw_speaker, "speaker") for raw_speaker in raw_speakers],
            words=[TranscriptMerger._validate_segment(raw_word, "word") for raw_word in raw_words],
        )

    @staticmethod
    def _validate_segment(raw_segment: object, label: str) -> TritonOutputSegment:
        if not isinstance(raw_segment, Mapping):
            raise TypeError(f"each {label} segment must be an object")
        start = raw_segment.get("start_timestamp")
        end = raw_segment.get("end_timestamp")
        value = raw_segment.get("value")
        if not isinstance(start, int | float):
            raise TypeError(f"{label} segment start_timestamp must be numeric")
        if not isinstance(end, int | float):
            raise TypeError(f"{label} segment end_timestamp must be numeric")
        if not isinstance(value, str):
            raise TypeError(f"{label} segment value must be a string")
        return TritonOutputSegment(
            start_timestamp=float(start),
            end_timestamp=float(end),
            value=value,
        )

    @staticmethod
    def _segment_to_item(
        raw_segment: TritonOutputSegment,
        rank: int,
    ) -> InterleavedTranscriptItem:
        segment_midpoint = 0.0

        if rank == _WORD_RANK:
            segment_midpoint = TranscriptMerger._calc_midpoint(
                raw_segment["start_timestamp"],
                raw_segment["end_timestamp"],
            )
        elif rank == _SPEAKER_RANK:
            segment_midpoint = raw_segment["start_timestamp"]

        return segment_midpoint, rank, raw_segment["value"]

    @staticmethod
    def _calc_midpoint(
        start_ts: float,
        end_ts: float,
    ) -> float:
        return (start_ts + end_ts) / 2
