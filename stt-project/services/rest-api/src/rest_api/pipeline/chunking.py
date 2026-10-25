"""Partition an uploaded audio file into fixed-size byte chunks.

stream-api treats chunk bytes opaquely (it base64-encodes and persists them
without transcoding), so partitioning is a pure byte-slicing operation with no
audio-format awareness.
"""

from __future__ import annotations

from collections.abc import Iterator


def iter_audio_chunks(data: bytes, chunk_size: int) -> Iterator[bytes]:
    """Yield ``data`` in contiguous slices of at most ``chunk_size`` bytes.

    Args:
        data: The full audio payload.
        chunk_size: Maximum size of each emitted chunk, in bytes.

    Yields:
        Non-empty byte slices in order. Empty input yields nothing.

    Raises:
        ValueError: If ``chunk_size`` is not positive.
    """
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be > 0, got: {chunk_size}")
    for start in range(0, len(data), chunk_size):
        yield data[start : start + chunk_size]
