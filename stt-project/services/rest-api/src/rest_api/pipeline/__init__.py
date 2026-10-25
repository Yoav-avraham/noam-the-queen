"""Pipeline layer: stream-api gRPC client, chunking, and transcript aggregation."""

from __future__ import annotations

from .types import StreamAck, StreamEvent, StreamResult, StreamFailure
from .chunking import iter_audio_chunks
from .aggregator import TranscriptAggregator
from .grpc_client import StreamAudioClient, create_channel

__all__ = [
    "StreamAck",
    "StreamAudioClient",
    "StreamEvent",
    "StreamFailure",
    "StreamResult",
    "TranscriptAggregator",
    "create_channel",
    "iter_audio_chunks",
]
