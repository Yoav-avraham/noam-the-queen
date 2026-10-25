"""Shared async Redis client for STT per-session streams.

This client owns the Redis connection lifecycle, exposes thin wrappers over the
raw Redis stream commands used across services, and provides the small set of
shared STT stream-contract helpers (active-session announcement, ``ServiceOutput``
serialization, per-session stream keys, and Redis entry parsing).

It deliberately knows only shared contracts (``ServiceOutput``, ``StreamName``,
``ACTIVE_STREAMS_KEY``, the ``data`` field, and ``{stream_name}:{session_id}``
keys). It does not know service-specific behavior such as audio chunks, gRPC
queues, routing, transcript merging, or inference details.
"""

from __future__ import annotations

from typing import Any
import logging
from urllib.parse import urlparse

import redis.asyncio as redis_asyncio
from redis.exceptions import ResponseError

from .constants import BUSYGROUP_TOKEN, GROUP_START_NEW_ENTRIES
from .contracts import (
    ACTIVE_STREAMS_KEY,
    StreamName,
    ServiceOutput,
    session_stream_key,
)

logger = logging.getLogger(__name__)

# Reply shape shared by ``xread``/``xreadgroup``: a list of
# ``(stream, [(entry_id, fields), ...])`` tuples.
RedisStreamReply = list[tuple[Any, list[tuple[Any, dict[bytes, bytes]]]]]

UNKNOWN_HOST = "unknown"


class RedisStreamClient:
    """Owns the Redis connection and shared STT stream operations."""

    # Redis field holding the serialized ServiceOutput envelope on data streams.
    DATA_FIELD = b"data"
    # Redis field holding the session id on the shared active_streams index.
    SESSION_ID_FIELD = "session_id"

    def __init__(self, redis_client: Any, *, redis_url: str | None = None) -> None:
        """Wrap an async Redis client; ``redis_url`` enables hostname logging."""
        self._redis_client = redis_client
        self._redis_url = redis_url

    @classmethod
    def from_url(cls, redis_url: str) -> RedisStreamClient:
        """Build a client from a Redis URL using ``redis.asyncio.from_url``."""
        return cls(redis_asyncio.from_url(redis_url), redis_url=redis_url)

    @property
    def redis_client(self) -> Any:
        """Return the wrapped async Redis client."""
        return self._redis_client

    @property
    def redis_hostname(self) -> str:
        """Return the Redis hostname for logging, or ``"unknown"``."""
        if self._redis_url is None:
            return UNKNOWN_HOST
        return urlparse(self._redis_url).hostname or UNKNOWN_HOST

    # --- lifecycle --------------------------------------------------------

    async def ping(self) -> None:
        """Verify connectivity, logging and re-raising on failure."""
        try:
            await self._redis_client.ping()
        except Exception:
            logger.exception(
                "failed to connect to redis",
                extra={"redis_host": self.redis_hostname},
            )
            raise

    async def aclose(self) -> None:
        """Close the underlying Redis connection."""
        await self._redis_client.aclose()

    # --- raw stream command wrappers -------------------------------------

    async def xadd(self, name: str, fields: dict[Any, Any]) -> Any:
        """Append one entry to a stream (server-assigned id)."""
        return await self._redis_client.xadd(name=name, fields=fields)

    async def xread(
        self,
        *,
        streams: dict[Any, Any],
        count: int | None = None,
        block: int | None = None,
    ) -> Any:
        """Read entries from one or more streams."""
        options: dict[str, Any] = {"streams": streams}

        if count is not None:
            options["count"] = count

        if block is not None:
            options["block"] = block

        return await self._redis_client.xread(**options)

    async def xreadgroup(
        self,
        *,
        groupname: str,
        consumername: str,
        streams: dict[Any, Any],
        count: int | None = None,
        block: int | None = None,
        claim_min_idle_time: int | None = None,
    ) -> Any:
        """Read entries for a consumer group, optionally claiming idle entries."""
        options: dict[str, Any] = {
            "groupname": groupname,
            "consumername": consumername,
            "streams": streams,
        }
        if count is not None:
            options["count"] = count
        if block is not None:
            options["block"] = block
        if claim_min_idle_time is not None:
            options["claim_min_idle_time"] = claim_min_idle_time
        return await self._redis_client.xreadgroup(**options)

    async def ensure_group(
        self,
        name: str,
        groupname: str,
        *,
        start_id: str = GROUP_START_NEW_ENTRIES,
        mkstream: bool = True,
    ) -> None:
        """Create a consumer group, treating an existing group as success.

        Idempotent: a ``BUSYGROUP`` reply (group already exists) is swallowed so
        callers can self-provision groups on every read/lease without races.
        ``start_id`` ``"$"`` consumes only new entries; ``"0"`` replays existing.
        """
        try:
            await self._redis_client.xgroup_create(
                name=name,
                groupname=groupname,
                id=start_id,
                mkstream=mkstream,
            )
        except ResponseError as exc:
            if BUSYGROUP_TOKEN in str(exc):
                return
            logger.exception(
                "failed creating consumer group",
                extra={"stream_key": name, "group": groupname},
            )
            raise

    async def xack(self, name: str, groupname: str, redis_id: str) -> Any:
        """Acknowledge one entry for a consumer group."""
        return await self._redis_client.xack(name, groupname, redis_id)

    async def xclaim(
        self,
        name: str,
        groupname: str,
        consumername: str,
        *,
        min_idle_time: int,
        message_ids: list[str],
    ) -> Any:
        """Claim ownership of pending entries for a consumer group."""
        return await self._redis_client.xclaim(
            name,
            groupname,
            consumername,
            min_idle_time=min_idle_time,
            message_ids=message_ids,
        )

    # --- shared STT stream helpers ---------------------------------------

    @staticmethod
    def stream_key(stream_name: StreamName | str, session_id: str) -> str:
        """Build one per-session stream key (``{stream_name}:{session_id}``)."""
        return session_stream_key(stream_name, session_id)

    async def announce_session(self, session_id: str) -> str:
        """Announce one active session in the shared active_streams index."""
        entry_id = await self.xadd(
            name=ACTIVE_STREAMS_KEY,
            fields={self.SESSION_ID_FIELD: session_id},
        )
        decoded_id = self._decode_entry_id(entry_id)
        logger.debug(
            "session announced to active_streams",
            extra={"session_id": session_id, "entry_id": decoded_id},
        )
        return decoded_id

    async def append_output(
        self,
        stream_name: StreamName | str,
        output: ServiceOutput,
    ) -> str:
        """Append one ``ServiceOutput`` envelope to its per-session stream."""
        stream_key = self.stream_key(stream_name, output.session_id)
        entry_id = await self.xadd(
            name=stream_key,
            fields={self.DATA_FIELD: output.model_dump_json().encode()},
        )
        decoded_id = self._decode_entry_id(entry_id)
        logger.debug(
            "output appended to stream",
            extra={
                "stream_key": stream_key,
                "session_id": output.session_id,
                "sequence_id": output.sequence_id,
                "is_final": output.is_final,
                "entry_id": decoded_id,
            },
        )
        return decoded_id

    @classmethod
    def parse_output(cls, fields: dict[bytes, bytes]) -> ServiceOutput:
        """Parse the serialized ``ServiceOutput`` envelope from stream fields."""
        return ServiceOutput.model_validate_json(fields[cls.DATA_FIELD])

    @staticmethod
    def to_str(value: str | bytes) -> str:
        """Decode a Redis value to ``str`` when it is returned as ``bytes``."""
        return value.decode() if isinstance(value, bytes) else value

    @staticmethod
    def entry_timestamp(redis_id: str) -> int:
        """Extract the millisecond timestamp from a Redis stream entry id."""
        return int(redis_id.split("-")[0])

    @staticmethod
    def _decode_entry_id(entry_id: str | bytes) -> str:
        return entry_id.decode("ascii") if isinstance(entry_id, bytes) else entry_id
