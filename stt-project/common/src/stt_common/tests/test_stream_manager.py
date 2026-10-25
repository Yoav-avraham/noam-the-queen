from __future__ import annotations

from typing import Any
import asyncio

import pytest
from redis.exceptions import ResponseError

from stt_common import stream_manager
from stt_common.contracts import StreamName, ServiceOutput, WindowPayload
from stt_common.stream_manager import SessionLease, StreamManager, StreamWorkItem
from stt_common.redis_stream_client import RedisStreamClient


class FakeRedis:
    """Minimal in-memory stand-in for redis.asyncio.Redis stream operations."""

    def __init__(self) -> None:
        self.ping_should_fail = False
        self.xreadgroup_calls: list[dict[str, Any]] = []
        self.xclaim_calls: list[dict[str, Any]] = []
        self.xadd_calls: list[dict[str, Any]] = []
        self.xack_calls: list[tuple[str, str, str]] = []
        self.xgroup_create_calls: list[dict[str, Any]] = []
        self.xgroup_create_exc: Exception | None = None

        # Queue of replies the fake returns for successive xreadgroup calls.
        self.xreadgroup_replies: list[Any] = []

    async def ping(self) -> bool:
        if self.ping_should_fail:
            raise ConnectionError("boom")
        return True

    async def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
        claim_min_idle_time: int | None = None,
    ) -> Any:
        self.xreadgroup_calls.append(
            {
                "groupname": groupname,
                "consumername": consumername,
                "streams": dict(streams),
                "count": count,
                "block": block,
                "claim_min_idle_time": claim_min_idle_time,
            },
        )
        if self.xreadgroup_replies:
            return self.xreadgroup_replies.pop(0)
        return []

    async def xclaim(
        self,
        name: str,
        groupname: str,
        consumername: str,
        min_idle_time: int,
        message_ids: list[str],
    ) -> list[Any]:
        self.xclaim_calls.append(
            {
                "name": name,
                "groupname": groupname,
                "consumername": consumername,
                "min_idle_time": min_idle_time,
                "message_ids": list(message_ids),
            },
        )
        return []

    async def xadd(self, name: str, fields: dict[bytes, bytes]) -> str:
        self.xadd_calls.append({"name": name, "fields": fields})
        return "1-0"

    async def xgroup_create(
        self,
        name: str,
        groupname: str,
        id: str = "$",
        mkstream: bool = False,
    ) -> bool:
        self.xgroup_create_calls.append(
            {"name": name, "groupname": groupname, "id": id, "mkstream": mkstream},
        )
        if self.xgroup_create_exc is not None:
            raise self.xgroup_create_exc
        return True

    async def xack(self, name: str, groupname: str, redis_id: str) -> int:
        self.xack_calls.append((name, groupname, redis_id))
        return 1


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


def make_manager(
    fake_redis: FakeRedis,
    handler: stream_manager.ServiceHandler | None = None,
    input_stream_name: StreamName | str = StreamName.TRITON_OUTPUT,
    output_stream_name: StreamName | str | None = None,
    consumer_name: str | None = "worker-1",
) -> StreamManager:
    async def default_handler(source: ServiceOutput) -> dict[str, Any]:
        return {
            "session_id": source.session_id,
            "field_count": len(source.window_payload.content),
        }

    return StreamManager(
        redis_client=RedisStreamClient(fake_redis),
        consumer_group_name="workers",
        input_stream_name=input_stream_name,
        service_handler=handler or default_handler,
        output_stream_name=output_stream_name,
        consumer_name=consumer_name,
    )


def data_fields(
    session_id: str = "s",
    *,
    sequence_id: int = 0,
    is_final: bool = False,
    content: dict[str, Any] | None = None,
    locale: str | None = None,
) -> dict[bytes, bytes]:
    """Build the redis fields for one per-session data entry (ServiceOutput)."""
    output = ServiceOutput(
        session_id=session_id,
        sequence_id=sequence_id,
        is_final=is_final,
        window_payload=WindowPayload(content=content or {}, locale=locale),
    )
    return {RedisStreamClient.DATA_FIELD: output.model_dump_json().encode()}


def test_init_resolves_stream_name_enum(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    assert manager.input_stream_name == "triton_output"
    # Output defaults to the next stream in the circular order.
    assert manager.output_stream_name == "final_output"
    assert manager.consumer_name == "worker-1"
    assert manager.redis_client.redis_client is fake_redis


def test_init_derives_output_for_each_stream(fake_redis: FakeRedis) -> None:
    def output_for(stream: StreamName) -> str:
        return make_manager(fake_redis, input_stream_name=stream).output_stream_name

    assert output_for(StreamName.READY_AUDIO) == "triton_output"
    assert output_for(StreamName.TRITON_OUTPUT) == "final_output"
    # The order wraps around: final feeds back to the first stream.
    assert output_for(StreamName.FINAL_OUTPUT) == "ready_audio"


def test_init_accepts_explicit_output_name(fake_redis: FakeRedis) -> None:
    manager = make_manager(
        fake_redis,
        input_stream_name="custom_in",
        output_stream_name="custom_out",
    )
    assert manager.input_stream_name == "custom_in"
    assert manager.output_stream_name == "custom_out"


def test_init_unknown_input_without_output_raises(fake_redis: FakeRedis) -> None:
    with pytest.raises(ValueError, match="cannot derive output stream"):
        make_manager(fake_redis, input_stream_name="custom_in")


def test_ensure_group_ignores_busygroup_response(fake_redis: FakeRedis) -> None:
    fake_redis.xgroup_create_exc = ResponseError("BUSYGROUP Consumer Group name already exists")
    manager = make_manager(fake_redis)

    asyncio.run(
        manager.redis_client.ensure_group(
            name="active_streams",
            groupname="workers",
        ),
    )

    assert fake_redis.xgroup_create_calls == [
        {"name": "active_streams", "groupname": "workers", "id": "$", "mkstream": True},
    ]


def test_ensure_group_propagates_other_response_errors(fake_redis: FakeRedis) -> None:
    fake_redis.xgroup_create_exc = ResponseError("ERR something else")
    manager = make_manager(fake_redis)

    with pytest.raises(ResponseError, match="ERR something else"):
        asyncio.run(
            manager.redis_client.ensure_group(
                name="active_streams",
                groupname="workers",
            ),
        )


def test_init_generates_consumer_name_when_missing(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis, consumer_name=None)
    assert manager.consumer_name.startswith("workers-")


def test_check_redis_connection_success(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    asyncio.run(manager.check_redis_connection())


def test_check_redis_connection_failure(fake_redis: FakeRedis) -> None:
    fake_redis.ping_should_fail = True
    manager = make_manager(fake_redis)
    with pytest.raises(ConnectionError):
        asyncio.run(manager.check_redis_connection())


def test_entry_timestamp_parses_millis(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    assert manager.redis_client.entry_timestamp("1700000000123-4") == 1700000000123


def test_parse_service_output_reads_envelope(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    fields = data_fields("sess", sequence_id=3, is_final=True, content={"text": "hi"})

    output = manager.redis_client.parse_output(fields)

    assert output.session_id == "sess"
    assert output.sequence_id == 3
    assert output.is_final is True
    assert output.window_payload.content == {"text": "hi"}


def test_build_stream_key(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    assert manager.redis_client.stream_key("triton_output", "abc") == "triton_output:abc"


def test_lease_sessions_registers_lease_and_stream(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    fake_redis.xreadgroup_replies = [
        [("active_streams", [("5-0", {b"session_id": b"sess-1"})])],
    ]

    asyncio.run(manager._lease_sessions())

    assert manager.leased_sessions["sess-1"].lease_id == "5-0"
    assert manager.leased_sessions["sess-1"].stream_key == "triton_output:sess-1"
    call = fake_redis.xreadgroup_calls[0]
    assert call["consumername"] == "worker-1"
    assert call["streams"] == {"active_streams": ">"}
    # A single read merges new and idle entries via claim-min-idle-time.
    assert call["claim_min_idle_time"] == manager.CLAIM_IDLE_MS
    assert call["count"] == manager.READ_BATCH_COUNT


def test_register_leased_sessions_does_not_duplicate_streams(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    messages = [("active_streams", [("1-0", {b"session_id": b"s"})])]
    asyncio.run(manager._register_leased_sessions(messages))
    asyncio.run(manager._register_leased_sessions(messages))
    assert list(manager.leased_sessions) == ["s"]
    assert manager.leased_sessions["s"].stream_key == "triton_output:s"


def test_heartbeat_session_renews_when_interval_elapsed(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    manager.leased_sessions = {"s": SessionLease(lease_id="1-0", stream_key="triton_output:s")}

    asyncio.run(manager._heartbeat_session("s"))

    call = fake_redis.xclaim_calls[0]
    assert call["min_idle_time"] == 0
    assert call["message_ids"] == ["1-0"]
    assert manager.leased_sessions["s"].last_heartbeat > 0.0


def test_heartbeat_session_throttles_within_interval(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    manager.leased_sessions = {"s": SessionLease(lease_id="1-0", stream_key="triton_output:s")}

    asyncio.run(manager._heartbeat_session("s"))
    asyncio.run(manager._heartbeat_session("s"))

    # Second call is within MIN_HEARTBEAT_INTERVAL_S, so no extra XCLAIM.
    assert len(fake_redis.xclaim_calls) == 1


def test_heartbeat_session_unknown_is_noop(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    asyncio.run(manager._heartbeat_session("nope"))
    assert fake_redis.xclaim_calls == []


def test_release_session_acks_index_and_clears_state(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    manager.leased_sessions = {
        "sess": SessionLease(
            lease_id="7-0",
            stream_key="triton_output:sess",
            last_heartbeat=123.0,
        ),
    }

    asyncio.run(manager._release_session("sess"))

    assert fake_redis.xack_calls == [("active_streams", "workers", "7-0")]
    assert manager.leased_sessions == {}


def test_release_session_unknown_is_noop(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    asyncio.run(manager._release_session("nope"))
    assert fake_redis.xack_calls == []


def test_build_work_items_sorts_by_entry_timestamp(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    messages = [
        (
            "triton_output:s",
            [
                ("200-0", data_fields("s")),
                ("100-0", data_fields("s", is_final=True)),
            ],
        ),
    ]

    items = manager._build_work_items(messages)

    assert [item.redis_id for item in items] == ["100-0", "200-0"]
    assert [item.entry_timestamp_ms for item in items] == [100, 200]
    assert items[0].is_final is True
    assert items[1].is_final is False


def test_build_work_items_skips_malformed_entries(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    messages = [
        (
            "triton_output:s",
            [
                ("100-0", {RedisStreamClient.DATA_FIELD: b"not-json"}),
                ("200-0", data_fields("s")),
            ],
        ),
    ]

    items = manager._build_work_items(messages)

    assert [item.redis_id for item in items] == ["200-0"]


def test_finalize_failed_work_item_acks_and_heartbeats_non_final(
    fake_redis: FakeRedis,
) -> None:
    manager = make_manager(fake_redis)
    manager.leased_sessions = {
        "s": SessionLease(lease_id="7-0", stream_key="triton_output:s"),
    }
    item = StreamWorkItem(
        stream_key="triton_output:s",
        redis_id="100-0",
        entry_timestamp_ms=100,
        service_output=ServiceOutput(
            session_id="s",
            sequence_id=1,
            is_final=False,
            window_payload=WindowPayload(content={}),
        ),
    )

    asyncio.run(manager._finalize_failed_work_item(item))

    assert ("triton_output:s", "workers", "100-0") in fake_redis.xack_calls
    assert fake_redis.xclaim_calls[0]["message_ids"] == ["7-0"]


def test_finalize_failed_work_item_acks_and_releases_final(
    fake_redis: FakeRedis,
) -> None:
    manager = make_manager(fake_redis)
    manager.leased_sessions = {
        "s": SessionLease(lease_id="7-0", stream_key="triton_output:s"),
    }
    item = StreamWorkItem(
        stream_key="triton_output:s",
        redis_id="100-0",
        entry_timestamp_ms=100,
        service_output=ServiceOutput(
            session_id="s",
            sequence_id=1,
            is_final=True,
            window_payload=WindowPayload(content={}),
        ),
    )

    asyncio.run(manager._finalize_failed_work_item(item))

    assert ("triton_output:s", "workers", "100-0") in fake_redis.xack_calls
    assert ("active_streams", "workers", "7-0") in fake_redis.xack_calls
    assert "s" not in manager.leased_sessions


def test_enqueue_claimed_messages_backs_off_when_no_streams(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    asyncio.run(manager._enqueue_claimed_messages())
    assert fake_redis.xreadgroup_calls == []


def test_enqueue_claimed_messages_queues_items(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    manager.leased_sessions = {"s": SessionLease(lease_id="0-0", stream_key="triton_output:s")}
    fake_redis.xreadgroup_replies = [
        [("triton_output:s", [("1-0", data_fields("s"))])],
    ]

    asyncio.run(manager._enqueue_claimed_messages())

    item = manager.work_queue.get_nowait()
    assert item.session_id == "s"
    assert item.redis_id == "1-0"
    # Per-session reads are unbounded (no count) so the whole backlog drains.
    assert fake_redis.xreadgroup_calls[0]["count"] is None


def test_process_work_item_publishes_and_acks_data_message(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    item = StreamWorkItem(
        stream_key="triton_output:s",
        redis_id="3-0",
        entry_timestamp_ms=3,
        service_output=ServiceOutput(
            session_id="s",
            sequence_id=7,
            is_final=False,
            window_payload=WindowPayload(content={"text": "hi"}, locale="en"),
        ),
    )

    asyncio.run(manager._process_work_item(item))

    add_call = fake_redis.xadd_calls[0]
    assert add_call["name"] == "final_output:s"
    published = ServiceOutput.model_validate_json(
        add_call["fields"][RedisStreamClient.DATA_FIELD],
    )
    # Envelope metadata is preserved; the handler output becomes the new content.
    assert published.session_id == "s"
    assert published.sequence_id == 7
    assert published.is_final is False
    assert published.window_payload.locale == "en"
    assert published.window_payload.content == {"session_id": "s", "field_count": 1}
    assert fake_redis.xack_calls == [("triton_output:s", "workers", "3-0")]


def test_process_work_item_releases_session_on_final(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    manager.leased_sessions = {"s": SessionLease(lease_id="4-0", stream_key="triton_output:s")}
    item = StreamWorkItem(
        stream_key="triton_output:s",
        redis_id="5-0",
        entry_timestamp_ms=5,
        service_output=ServiceOutput(
            session_id="s",
            sequence_id=1,
            is_final=True,
            window_payload=WindowPayload(content={}),
        ),
    )

    asyncio.run(manager._process_work_item(item))

    # Data message acked on its stream, and the session lease acked on the index.
    assert ("triton_output:s", "workers", "5-0") in fake_redis.xack_calls
    assert ("active_streams", "workers", "4-0") in fake_redis.xack_calls
    assert manager.leased_sessions == {}


def test_process_work_item_heartbeats_session_on_non_final(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    manager.leased_sessions = {"s": SessionLease(lease_id="4-0", stream_key="triton_output:s")}
    item = StreamWorkItem(
        stream_key="triton_output:s",
        redis_id="5-0",
        entry_timestamp_ms=5,
        service_output=ServiceOutput(
            session_id="s",
            sequence_id=1,
            is_final=False,
            window_payload=WindowPayload(content={}),
        ),
    )

    asyncio.run(manager._process_work_item(item))

    # Non-final message renews the lease instead of releasing it.
    assert fake_redis.xclaim_calls[0]["message_ids"] == ["4-0"]
    assert list(manager.leased_sessions) == ["s"]


def test_consume_work_items_processes_queue(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    item = StreamWorkItem(
        stream_key="triton_output:s",
        redis_id="1-0",
        entry_timestamp_ms=1,
        service_output=ServiceOutput(
            session_id="s",
            sequence_id=0,
            is_final=False,
            window_payload=WindowPayload(content={}),
        ),
    )
    manager.work_queue.put_nowait(item)

    async def run_once() -> None:
        task = asyncio.create_task(manager.consume_work_items())
        await manager.work_queue.join()
        task.cancel()

    asyncio.run(run_once())

    assert fake_redis.xadd_calls


def test_consume_work_items_swallows_handler_errors(fake_redis: FakeRedis) -> None:
    async def failing_handler(source: ServiceOutput) -> dict[str, Any]:
        _ = source
        raise RuntimeError("handler boom")

    manager = make_manager(fake_redis, handler=failing_handler)
    manager.work_queue.put_nowait(
        StreamWorkItem(
            stream_key="triton_output:s",
            redis_id="1-0",
            entry_timestamp_ms=1,
            service_output=ServiceOutput(
                session_id="s",
                sequence_id=0,
                is_final=False,
                window_payload=WindowPayload(content={}),
            ),
        ),
    )

    async def run_once() -> None:
        task = asyncio.create_task(manager.consume_work_items())
        await manager.work_queue.join()
        task.cancel()

    # The loop logs and keeps running rather than crashing.
    asyncio.run(run_once())
    assert fake_redis.xadd_calls == []


async def _run_loop_once(coro_factory: Any) -> None:
    """Start an infinite loop coroutine, let it iterate once, then cancel it."""
    task = asyncio.create_task(coro_factory())
    try:
        await asyncio.sleep(0.05)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def test_ingest_active_sessions_handles_exceptions(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    calls: list[int] = []

    async def lease() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("lease boom")  # exercised by the except handler
        raise asyncio.CancelledError  # break out of the infinite loop

    manager._lease_sessions = lease  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(manager.ingest_active_sessions())
    # First iteration's error was swallowed; the loop continued to a second one.
    assert len(calls) == 2


def test_produce_work_items_enqueues_from_loop(fake_redis: FakeRedis) -> None:
    manager = make_manager(fake_redis)
    manager.leased_sessions = {"s": SessionLease(lease_id="0-0", stream_key="triton_output:s")}
    fake_redis.xreadgroup_replies = [
        [("triton_output:s", [("1-0", data_fields("s"))])],
    ]
    original = manager._enqueue_claimed_messages

    async def enqueue_once() -> None:
        await original()
        raise asyncio.CancelledError

    manager._enqueue_claimed_messages = enqueue_once  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(manager.produce_work_items())
    assert not manager.work_queue.empty()


def test_run_workers_starts_all_loops(
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = make_manager(fake_redis)
    started: set[str] = set()

    def make_noop(name: str) -> Any:
        async def _noop() -> None:
            started.add(name)

        return _noop

    for loop_name in (
        "ingest_active_sessions",
        "produce_work_items",
        "consume_work_items",
    ):
        monkeypatch.setattr(manager, loop_name, make_noop(loop_name))

    asyncio.run(manager.run_workers())

    assert started == {
        "ingest_active_sessions",
        "produce_work_items",
        "consume_work_items",
    }
