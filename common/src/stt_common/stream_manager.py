from __future__ import annotations

import time
import uuid
from typing import Any
import asyncio
import logging
from dataclasses import dataclass
from collections.abc import Callable, Awaitable

from stt_common.constants import (
    ENTRY_ID_INDEX,
    ENTRY_FIELDS_INDEX,
    READ_NEW_MESSAGES_ID,
    STREAM_REPLY_KEY_INDEX,
    GROUP_START_ALL_ENTRIES,
    STREAM_REPLY_ENTRIES_INDEX,
)
from stt_common.contracts import (
    ACTIVE_STREAMS_KEY,
    StreamName,
    ServiceOutput,
    WindowPayload,
)
from stt_common.redis_stream_client import RedisStreamReply, RedisStreamClient

logger = logging.getLogger(__name__)

ServiceHandler = Callable[[ServiceOutput], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class StreamWorkItem:
    """One per-session data message read from a claimed stream."""

    stream_key: str
    redis_id: str
    entry_timestamp_ms: int
    service_output: ServiceOutput

    @property
    def session_id(self) -> str:
        return self.service_output.session_id

    @property
    def is_final(self) -> bool:
        return self.service_output.is_final


@dataclass(slots=True)
class SessionLease:
    """Bookkeeping for one session leased from the active_streams index."""

    # Entry id of the session's lease in the active_streams index (used to renew
    # via XCLAIM and to release via XACK).
    lease_id: str
    # Per-session data stream key (``{service_output_name}:{session_id}``); fixed
    # for the lease's lifetime, so it is computed once at lease time.
    stream_key: str
    # Monotonic time of the last lease heartbeat, for throttling renewals.
    last_heartbeat: float = 0.0


class StreamManager:
    """Leases sessions from a shared Redis index and processes their data streams.

    See ``docs/contributor/services/common/README.md`` for the leasing and
    per-session data-stream topology.
    """

    MAX_BLOCK_TIME_MS = 1000  # XREADGROUP block window
    CLAIM_IDLE_MS = 30 * 1000  # also lease index entries idle longer than this
    MIN_HEARTBEAT_INTERVAL_S = 2.0  # min gap between a session's lease renewals
    IDLE_POLL_S = 0.1  # backoff when no streams are claimed yet
    READ_BATCH_COUNT = 10

    def __init__(
        self,
        redis_client: RedisStreamClient,
        consumer_group_name: str,
        input_stream_name: StreamName | str,
        service_handler: ServiceHandler,
        output_stream_name: StreamName | str | None = None,
        consumer_name: str | None = None,
        active_streams_key: str = ACTIVE_STREAMS_KEY,
    ) -> None:
        self.consumer_group_name = consumer_group_name
        self.consumer_name = consumer_name or f"{consumer_group_name}-{uuid.uuid4().hex[:8]}"
        self.active_streams_key = active_streams_key
        # The service reads/leases sessions from ``input_stream_name`` and pushes
        # results to ``output_stream_name``. When the output is not given, it is
        # the next stream in the circular pipeline order (see StreamName.next).
        self.input_stream_name = self._resolve_stream_name(input_stream_name)
        self.output_stream_name = self._resolve_output_stream_name(
            input_stream_name,
            output_stream_name,
        )
        self.service_handler = service_handler
        self.redis_client = redis_client
        self.leased_sessions: dict[str, SessionLease] = {}
        self.work_queue: asyncio.Queue[StreamWorkItem] = asyncio.Queue()

    async def check_redis_connection(self) -> None:
        await self.redis_client.ping()

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _resolve_stream_name(stream_name: StreamName | str) -> str:
        return stream_name.value if isinstance(stream_name, StreamName) else stream_name

    @classmethod
    def _resolve_output_stream_name(
        cls,
        input_stream_name: StreamName | str,
        output_stream_name: StreamName | str | None,
    ) -> str:
        if output_stream_name is not None:
            return cls._resolve_stream_name(output_stream_name)
        # Derive the next stream in the circular pipeline order. A raw string is
        # only derivable if it maps to a known StreamName; otherwise the caller
        # must pass ``output_stream_name`` explicitly.
        if not isinstance(input_stream_name, StreamName):
            try:
                input_stream_name = StreamName(input_stream_name)
            except ValueError as error:
                raise ValueError(
                    f"cannot derive output stream from unknown input stream "
                    f"{input_stream_name!r}; pass output_stream_name explicitly",
                ) from error
        return input_stream_name.next().value

    # --- session leasing (active_streams index) ---------------------------

    async def ingest_active_sessions(self) -> None:
        """Continuously lease newly-announced and idle/abandoned sessions."""
        await self.redis_client.ensure_group(
            self.active_streams_key,
            self.consumer_group_name,
        )
        while True:
            try:
                await self._lease_sessions()
            except Exception:
                logger.exception("failed leasing active sessions")

    async def _lease_sessions(self) -> None:
        messages = await self.redis_client.xreadgroup(
            groupname=self.consumer_group_name,
            consumername=self.consumer_name,
            streams={self.active_streams_key: READ_NEW_MESSAGES_ID},
            count=self.READ_BATCH_COUNT,
            block=self.MAX_BLOCK_TIME_MS,
            claim_min_idle_time=self.CLAIM_IDLE_MS,
        )
        await self._register_leased_sessions(messages or [])

    async def _register_leased_sessions(self, messages: RedisStreamReply) -> None:
        # CLAIM-mode entries carry trailing metadata: (id, fields, *meta); take id+fields.
        for stream_reply in messages:
            entries = stream_reply[STREAM_REPLY_ENTRIES_INDEX]
            for entry in entries:
                entry_id, fields = entry[ENTRY_ID_INDEX], entry[ENTRY_FIELDS_INDEX]
                session_id = self.redis_client.to_str(fields[b"session_id"])
                lease_id = self.redis_client.to_str(entry_id)
                lease = self.leased_sessions.get(session_id)
                if lease is None:
                    stream_key = self.redis_client.stream_key(self.input_stream_name, session_id)
                    await self.redis_client.ensure_group(
                        stream_key,
                        self.consumer_group_name,
                        start_id=GROUP_START_ALL_ENTRIES,
                    )
                    self.leased_sessions[session_id] = SessionLease(
                        lease_id=lease_id,
                        stream_key=stream_key,
                    )
                else:
                    lease.lease_id = lease_id

    async def _heartbeat_session(self, session_id: str) -> None:
        lease = self.leased_sessions.get(session_id)
        if lease is None:
            return
        now = time.monotonic()
        if now - lease.last_heartbeat < self.MIN_HEARTBEAT_INTERVAL_S:
            return
        await self.redis_client.xclaim(
            self.active_streams_key,
            self.consumer_group_name,
            self.consumer_name,
            min_idle_time=0,
            message_ids=[lease.lease_id],
        )
        lease.last_heartbeat = now

    async def _release_session(self, session_id: str) -> None:
        lease = self.leased_sessions.pop(session_id, None)
        if lease is not None:
            await self.redis_client.xack(
                self.active_streams_key,
                self.consumer_group_name,
                lease.lease_id,
            )

    # --- per-session data streams ----------------------------------------

    async def produce_work_items(self) -> None:
        """Read data messages from claimed streams and queue them in time order."""
        while True:
            try:
                await self._enqueue_claimed_messages()
            except Exception:
                logger.exception("failed reading data messages")

    async def _enqueue_claimed_messages(self) -> None:
        if not self.leased_sessions:
            await asyncio.sleep(self.IDLE_POLL_S)
            return

        messages = await self.redis_client.xreadgroup(
            groupname=self.consumer_group_name,
            consumername=self.consumer_name,
            streams={lease.stream_key: READ_NEW_MESSAGES_ID for lease in self.leased_sessions.values()},
            block=self.MAX_BLOCK_TIME_MS,
        )
        if not messages:
            return

        for item in self._build_work_items(messages):
            await self.work_queue.put(item)

    def _build_work_items(self, messages: RedisStreamReply) -> list[StreamWorkItem]:
        items: list[StreamWorkItem] = []
        for stream_reply in messages:
            stream_key = stream_reply[STREAM_REPLY_KEY_INDEX]
            entries = stream_reply[STREAM_REPLY_ENTRIES_INDEX]
            key = self.redis_client.to_str(stream_key)
            for entry in entries:
                entry_id, fields = entry[ENTRY_ID_INDEX], entry[ENTRY_FIELDS_INDEX]
                redis_id = self.redis_client.to_str(entry_id)
                try:
                    service_output = self.redis_client.parse_output(fields)
                except Exception:
                    logger.exception(
                        "failed parsing data message",
                        extra={"stream_key": key, "redis_id": redis_id},
                    )
                    continue
                items.append(
                    StreamWorkItem(
                        stream_key=key,
                        redis_id=redis_id,
                        entry_timestamp_ms=self.redis_client.entry_timestamp(redis_id),
                        service_output=service_output,
                    ),
                )
        items.sort(key=lambda item: item.entry_timestamp_ms)
        return items

    async def consume_work_items(self) -> None:
        """Process queued data messages, publish results, and ack appropriately."""
        while True:
            item = await self.work_queue.get()
            try:
                await self._process_work_item(item)
            except Exception:
                logger.exception(
                    "failed processing data message",
                    extra={"session_id": item.session_id, "redis_id": item.redis_id},
                )
                try:
                    await self._finalize_failed_work_item(item)
                except Exception:
                    logger.exception(
                        "failed finalizing failed data message",
                        extra={"session_id": item.session_id, "redis_id": item.redis_id},
                    )
            finally:
                self.work_queue.task_done()

    async def _process_work_item(self, item: StreamWorkItem) -> None:
        source = item.service_output
        content = await self.service_handler(source)

        output = ServiceOutput(
            session_id=source.session_id,
            sequence_id=source.sequence_id,
            is_final=source.is_final,
            window_payload=WindowPayload(content=content, locale=source.window_payload.locale),
        )
        await self.redis_client.append_output(self.output_stream_name, output)

        await self._ack_data_message(item.stream_key, item.redis_id)

        if source.is_final:
            await self._release_session(source.session_id)
        else:
            await self._heartbeat_session(source.session_id)

    async def _ack_data_message(self, stream_key: str, redis_id: str) -> None:
        await self.redis_client.xack(stream_key, self.consumer_group_name, redis_id)

    async def _finalize_failed_work_item(self, item: StreamWorkItem) -> None:
        """Ack a failed message and advance session lifecycle to avoid stalls."""
        await self._ack_data_message(item.stream_key, item.redis_id)
        if item.is_final:
            await self._release_session(item.session_id)
        else:
            await self._heartbeat_session(item.session_id)

    async def run_workers(self) -> None:
        await asyncio.gather(
            self.ingest_active_sessions(),
            self.produce_work_items(),
            self.consume_work_items(),
        )
