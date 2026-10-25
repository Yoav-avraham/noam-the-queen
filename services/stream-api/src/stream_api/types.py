from __future__ import annotations

import asyncio

from .proto import audio_ingest_pb2 as pb2

ServerEventQueue = asyncio.Queue[pb2.ServerEvent | None]
