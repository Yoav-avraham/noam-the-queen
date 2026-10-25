"""Generated protobuf modules for the stream API."""

from __future__ import annotations

import sys

from . import audio_ingest_pb2

# grpc_tools generates absolute imports (import audio_ingest_pb2) in *_pb2_grpc.py.
# Register a deterministic alias so those imports resolve to this package's module.
sys.modules["audio_ingest_pb2"] = audio_ingest_pb2
