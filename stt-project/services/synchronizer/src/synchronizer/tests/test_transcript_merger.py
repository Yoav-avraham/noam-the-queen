from __future__ import annotations

from typing import cast

import pytest

from stt_common.contracts import TritonOutputSegment, TritonOutputWindowContent
from synchronizer.transcript_merger import TranscriptMerger

HEBREW_LABEL = "דובר"


def _merge(
    merger: TranscriptMerger,
    *,
    session_id: str = "session-1",
    content: TritonOutputWindowContent,
    locale: str | None = "en",
    is_final: bool = False,
) -> str:
    return merger.merge_window(
        session_id=session_id,
        content=content,
        locale=locale,
        is_final=is_final,
    ).finalized_text


def _speaker(speaker_id: str, start: float, end: float | None = None) -> TritonOutputSegment:
    return {
        "start_timestamp": start,
        "end_timestamp": start if end is None else end,
        "value": speaker_id,
    }


def _word(word: str, start: float, end: float | None = None) -> TritonOutputSegment:
    return {
        "start_timestamp": start,
        "end_timestamp": start if end is None else end,
        "value": word,
    }


def test_merge_interleaves_words_under_single_speaker() -> None:
    merger = TranscriptMerger()
    content: TritonOutputWindowContent = {
        "speakers": [_speaker("1", 0.0)],
        "words": [_word("hello", 0.1), _word("world", 0.5)],
    }

    assert _merge(merger, content=content, locale="en") == "\nSpeaker 1: hello world"


def test_merge_uses_hebrew_label_when_locale_missing() -> None:
    merger = TranscriptMerger()
    content: TritonOutputWindowContent = {
        "speakers": [_speaker("1", 0.0)],
        "words": [_word("shalom", 0.1)],
    }

    assert _merge(merger, content=content, locale=None) == f"\n{HEBREW_LABEL} 1: shalom"


@pytest.mark.parametrize(
    ("locale", "expected_label"),
    [
        (None, HEBREW_LABEL),
        ("", HEBREW_LABEL),
        ("he", HEBREW_LABEL),
        ("he-IL", HEBREW_LABEL),
        ("en", "Speaker"),
        ("en-US", "Speaker"),
        ("en_GB", "Speaker"),
        ("fr", HEBREW_LABEL),
        ("zz-ZZ", HEBREW_LABEL),
    ],
)
def test_merge_localizes_label_with_hebrew_fallback(locale: str | None, expected_label: str) -> None:
    merger = TranscriptMerger()
    content: TritonOutputWindowContent = {
        "speakers": [_speaker("1", 0.0)],
        "words": [_word("x", 0.1)],
    }

    assert _merge(merger, content=content, locale=locale) == f"\n{expected_label} 1: x"


def test_merge_labels_each_distinct_speaker_on_its_own_line() -> None:
    merger = TranscriptMerger()
    content: TritonOutputWindowContent = {
        "speakers": [_speaker("1", 0.0), _speaker("2", 1.0)],
        "words": [_word("a", 0.1), _word("b", 1.1)],
    }

    assert _merge(merger, content=content, locale="en") == "\nSpeaker 1: a\nSpeaker 2: b"


def test_merge_suppresses_label_for_same_speaker_within_window() -> None:
    merger = TranscriptMerger()
    content: TritonOutputWindowContent = {
        "speakers": [_speaker("1", 0.0), _speaker("1", 1.0)],
        "words": [_word("a", 0.1), _word("b", 1.1)],
    }

    assert _merge(merger, content=content, locale="en") == "\nSpeaker 1: a b"


def test_merge_attributes_tied_word_to_the_new_speaker() -> None:
    merger = TranscriptMerger()
    # "b" starts exactly when speaker 2 starts; the speaker marker sorts first,
    # so "b" is attributed to speaker 2, not the trailing edge of speaker 1.
    content: TritonOutputWindowContent = {
        "speakers": [_speaker("1", 0.0), _speaker("2", 1.0)],
        "words": [_word("a", 0.0), _word("b", 1.0)],
    }

    assert _merge(merger, content=content, locale="en") == "\nSpeaker 1: a\nSpeaker 2: b"


def test_merge_suppresses_label_when_first_speaker_continues_previous_window() -> None:
    merger = TranscriptMerger()
    first: TritonOutputWindowContent = {
        "speakers": [_speaker("1", 0.0)],
        "words": [_word("hello", 0.1)],
    }
    second: TritonOutputWindowContent = {
        "speakers": [_speaker("1", 0.0)],
        "words": [_word("world", 0.1)],
    }

    assert _merge(merger, content=first, locale="en") == "\nSpeaker 1: hello"
    # Same speaker continues across the window boundary: label suppressed.
    assert _merge(merger, content=second, locale="en") == "world"


def test_merge_keeps_label_when_first_speaker_differs_across_window_boundary() -> None:
    merger = TranscriptMerger()
    first: TritonOutputWindowContent = {
        "speakers": [_speaker("1", 0.0)],
        "words": [_word("hello", 0.1)],
    }
    second: TritonOutputWindowContent = {
        "speakers": [_speaker("2", 0.0)],
        "words": [_word("world", 0.1)],
    }

    assert _merge(merger, content=first, locale="en") == "\nSpeaker 1: hello"
    assert _merge(merger, content=second, locale="en") == "\nSpeaker 2: world"


def test_merge_emits_orphan_words_without_a_label() -> None:
    merger = TranscriptMerger()
    # A word starting before any speaker marker has no open turn.
    content: TritonOutputWindowContent = {
        "speakers": [_speaker("1", 1.0)],
        "words": [_word("hi", 0.0), _word("bob", 1.1)],
    }

    assert _merge(merger, content=content, locale="en") == "hi\nSpeaker 1: bob"


def test_merge_empty_window_yields_empty_text() -> None:
    merger = TranscriptMerger()
    assert _merge(merger, content=TritonOutputWindowContent(), locale="en") == ""


def test_merge_final_clears_session_state() -> None:
    merger = TranscriptMerger()
    first: TritonOutputWindowContent = {
        "speakers": [_speaker("1", 0.0)],
        "words": [_word("hello", 0.1)],
    }
    second: TritonOutputWindowContent = {
        "speakers": [_speaker("1", 0.0)],
        "words": [_word("world", 0.1)],
    }

    # Finalizing clears continuation state, so the next window re-labels.
    assert _merge(merger, content=first, locale="en", is_final=True) == "\nSpeaker 1: hello"
    assert _merge(merger, content=second, locale="en") == "\nSpeaker 1: world"


def test_merge_isolates_state_per_session() -> None:
    merger = TranscriptMerger()
    first: TritonOutputWindowContent = {
        "speakers": [_speaker("1", 0.0)],
        "words": [_word("hello", 0.1)],
    }
    other: TritonOutputWindowContent = {
        "speakers": [_speaker("1", 0.0)],
        "words": [_word("world", 0.1)],
    }

    assert _merge(merger, session_id="a", content=first, locale="en") == "\nSpeaker 1: hello"
    # Different session has no prior speaker, so the label is kept.
    assert _merge(merger, session_id="b", content=other, locale="en") == "\nSpeaker 1: world"


def test_merge_rejects_malformed_shapes() -> None:
    merger = TranscriptMerger()
    with pytest.raises(TypeError):
        _merge(
            merger,
            content=cast(TritonOutputWindowContent, {"speakers": "not-a-list"}),
            locale="en",
        )
    with pytest.raises(TypeError):
        _merge(
            merger,
            content=cast(TritonOutputWindowContent, {"speakers": ["not-an-object"]}),
            locale="en",
        )
    with pytest.raises(TypeError):
        _merge(
            merger,
            content=cast(TritonOutputWindowContent, {"words": "not-a-list"}),
            locale="en",
        )
    with pytest.raises(TypeError):
        _merge(
            merger,
            content=cast(
                TritonOutputWindowContent,
                {"speakers": [{"start_timestamp": 0.0, "end_timestamp": 0.1}]},
            ),
            locale="en",
        )
    with pytest.raises(TypeError):
        _merge(
            merger,
            content=cast(
                TritonOutputWindowContent,
                {
                    "speakers": [
                        {
                            "start_timestamp": "0.0",
                            "end_timestamp": 0.1,
                            "value": "1",
                        }
                    ]
                },
            ),
            locale="en",
        )
