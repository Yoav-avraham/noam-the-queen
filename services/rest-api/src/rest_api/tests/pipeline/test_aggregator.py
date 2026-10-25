"""Tests for transcript aggregation."""

from __future__ import annotations

from rest_api.pipeline import TranscriptAggregator


def test_empty_aggregator_builds_empty_transcript() -> None:
    result = TranscriptAggregator().build()
    assert result.text == ""


def test_final_segments_are_concatenated_in_arrival_order() -> None:
    agg = TranscriptAggregator()
    agg.add_result(text="hello", is_final=True)
    agg.add_result(text="world", is_final=True)

    result = agg.build()

    assert result.text == "hello world"


def test_partials_only_returns_latest_non_empty() -> None:
    agg = TranscriptAggregator()
    agg.add_result(text="hel", is_final=False)
    agg.add_result(text="hello", is_final=False)

    result = agg.build()

    assert result.text == "hello"


def test_has_final_flag() -> None:
    agg = TranscriptAggregator()
    assert agg.has_final is False
    agg.add_result(text="x", is_final=True)
    assert agg.has_final is True


def test_sequence_numbers_are_assigned_in_arrival_order() -> None:
    agg = TranscriptAggregator()
    first = agg.add_result(text="a", is_final=False)
    second = agg.add_result(text="b", is_final=False)
    assert (first.sequence, second.sequence) == (0, 1)


def test_blank_final_segments_are_skipped_in_text() -> None:
    agg = TranscriptAggregator()
    agg.add_result(text="  ", is_final=True)
    agg.add_result(text="done", is_final=True)
    assert agg.build().text == "done"
