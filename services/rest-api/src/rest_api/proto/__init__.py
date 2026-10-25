"""Generated protobuf modules for the rest API gRPC client.

These stubs are generated from proto/audio_ingest.proto (a vendored copy of the
stream-api contract). Do not hand-edit the generated *_pb2*.py / *.pyi files;
regenerate them instead. See services/rest-api/README.md for the command.
"""

from __future__ import annotations

import sys

from . import audio_ingest_pb2

# grpc_tools generates absolute imports (import audio_ingest_pb2) in *_pb2_grpc.py.
# Register a deterministic alias so those imports resolve to this package's module.
sys.modules["audio_ingest_pb2"] = audio_ingest_pb2
