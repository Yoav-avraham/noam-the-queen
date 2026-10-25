"""Tests for audio chunking helpers."""

from __future__ import annotations

import pytest

from rest_api.pipeline import iter_audio_chunks


def test_iter_chunks_splits_evenly() -> None:
    data = b"abcdefgh"
    assert list(iter_audio_chunks(data, 4)) == [b"abcd", b"efgh"]


def test_iter_chunks_handles_remainder() -> None:
    data = b"abcdefg"
    assert list(iter_audio_chunks(data, 3)) == [b"abc", b"def", b"g"]


def test_iter_chunks_empty_yields_nothing() -> None:
    assert list(iter_audio_chunks(b"", 4)) == []


def test_iter_chunks_chunk_larger_than_data() -> None:
    assert list(iter_audio_chunks(b"ab", 16)) == [b"ab"]


def test_iter_chunks_rejects_non_positive_size() -> None:
    with pytest.raises(ValueError):
        list(iter_audio_chunks(b"abc", 0))
