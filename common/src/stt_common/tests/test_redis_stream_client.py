from __future__ import annotations

import json
from typing import Any
import asyncio

import pytest

from stt_common.contracts import StreamName, ServiceOutput, WindowPayload
from stt_common.redis_stream_client import RedisStreamClient


class FakeRawRedis:
    """Minimal in-memory stand-in for ``redis.asyncio.Redis``."""

    def __init__(self) -> None:
        self.ping_should_fail = False
        self.closed = False
        self.xadd_calls: list[dict[str, Any]] = []
        self.xread_calls: list[dict[str, Any]] = []
        self.xreadgroup_calls: list[dict[str, Any]] = []
        self.xack_calls: list[tuple[str, str, str]] = []
        self.xclaim_calls: list[dict[str, Any]] = []
        self._next_id = 1

    async def ping(self) -> bool:
        if self.ping_should_fail:
            raise ConnectionError("boom")
        return True

    async def aclose(self) -> None:
        self.closed = True

    async def xadd(self, name: str, fields: dict[Any, Any]) -> bytes:
        self.xadd_calls.append({"name": name, "fields": fields})
        entry_id = f"{self._next_id}-0".encode("ascii")
        self._next_id += 1
        return entry_id

    async def xread(self, **kwargs: Any) -> Any:
        self.xread_calls.append(kwargs)
        return []

    async def xreadgroup(self, **kwargs: Any) -> Any:
        self.xreadgroup_calls.append(kwargs)
        return []

    async def xack(self, name: str, groupname: str, redis_id: str) -> int:
        self.xack_calls.append((name, groupname, redis_id))
        return 1

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


def make_output(
    session_id: str = "s",
    *,
    sequence_id: int = 1,
    is_final: bool = False,
    content: dict[str, Any] | None = None,
) -> ServiceOutput:
    return ServiceOutput(
        session_id=session_id,
        sequence_id=sequence_id,
        is_final=is_final,
        window_payload=WindowPayload(content=content or {"text": "hi"}),
    )


def test_from_url_exposes_hostname() -> None:
    client = RedisStreamClient.from_url("redis://example-host:6379/0")
    assert client.redis_hostname == "example-host"


def test_redis_hostname_unknown_without_url() -> None:
    client = RedisStreamClient(FakeRawRedis())
    assert client.redis_hostname == "unknown"


def test_ping_success() -> None:
    client = RedisStreamClient(FakeRawRedis())
    asyncio.run(client.ping())


def test_ping_failure_raises() -> None:
    fake = FakeRawRedis()
    fake.ping_should_fail = True
    client = RedisStreamClient(fake)
    with pytest.raises(ConnectionError):
        asyncio.run(client.ping())


def test_aclose_closes_underlying_client() -> None:
    fake = FakeRawRedis()
    client = RedisStreamClient(fake)
    asyncio.run(client.aclose())
    assert fake.closed is True


def test_announce_session_writes_active_streams_index() -> None:
    fake = FakeRawRedis()
    client = RedisStreamClient(fake)

    entry_id = asyncio.run(client.announce_session("session-abc"))

    assert entry_id == "1-0"
    assert fake.xadd_calls == [
        {"name": "active_streams", "fields": {"session_id": "session-abc"}},
    ]


def test_append_output_serializes_envelope_to_session_stream() -> None:
    fake = FakeRawRedis()
    client = RedisStreamClient(fake)
    output = make_output("session-abc", sequence_id=42, is_final=True)

    entry_id = asyncio.run(client.append_output(StreamName.READY_AUDIO, output))

    assert entry_id == "1-0"
    assert len(fake.xadd_calls) == 1
    call = fake.xadd_calls[0]
    assert call["name"] == "ready_audio:session-abc"
    assert set(call["fields"]) == {RedisStreamClient.DATA_FIELD}
    payload = json.loads(call["fields"][RedisStreamClient.DATA_FIELD])
    assert payload["session_id"] == "session-abc"
    assert payload["sequence_id"] == 42
    assert payload["is_final"] is True


def test_parse_output_reads_envelope_from_bytes_field() -> None:
    output = make_output("sess", sequence_id=3, is_final=True, content={"text": "hi"})
    fields = {RedisStreamClient.DATA_FIELD: output.model_dump_json().encode()}

    parsed = RedisStreamClient.parse_output(fields)

    assert parsed.session_id == "sess"
    assert parsed.sequence_id == 3
    assert parsed.is_final is True
    assert parsed.window_payload.content == {"text": "hi"}


def test_parse_output_missing_data_field_raises() -> None:
    with pytest.raises(KeyError):
        RedisStreamClient.parse_output({})


def test_to_str_decodes_bytes() -> None:
    assert RedisStreamClient.to_str(b"abc") == "abc"
    assert RedisStreamClient.to_str("abc") == "abc"


def test_entry_timestamp_parses_millis() -> None:
    assert RedisStreamClient.entry_timestamp("1700000000123-4") == 1700000000123


def test_stream_key_includes_session_id() -> None:
    assert RedisStreamClient.stream_key(StreamName.FINAL_OUTPUT, "abc") == "final_output:abc"


def test_xread_omits_unset_options() -> None:
    fake = FakeRawRedis()
    client = RedisStreamClient(fake)

    asyncio.run(client.xread(streams={"k": "0-0"}))

    assert fake.xread_calls == [{"streams": {"k": "0-0"}}]


def test_xreadgroup_forwards_only_provided_options() -> None:
    fake = FakeRawRedis()
    client = RedisStreamClient(fake)

    asyncio.run(
        client.xreadgroup(
            groupname="g",
            consumername="c",
            streams={"active_streams": ">"},
            count=10,
            block=1000,
            claim_min_idle_time=30000,
        )
    )

    assert fake.xreadgroup_calls == [
        {
            "groupname": "g",
            "consumername": "c",
            "streams": {"active_streams": ">"},
            "count": 10,
            "block": 1000,
            "claim_min_idle_time": 30000,
        }
    ]


def test_xreadgroup_without_count_or_claim() -> None:
    fake = FakeRawRedis()
    client = RedisStreamClient(fake)

    asyncio.run(
        client.xreadgroup(
            groupname="g",
            consumername="c",
            streams={"k": ">"},
            block=1000,
        )
    )

    call = fake.xreadgroup_calls[0]
    assert "count" not in call
    assert "claim_min_idle_time" not in call
    assert call["block"] == 1000


def test_xack_forwards_positional_arguments() -> None:
    fake = FakeRawRedis()
    client = RedisStreamClient(fake)

    asyncio.run(client.xack("stream", "group", "1-0"))

    assert fake.xack_calls == [("stream", "group", "1-0")]


def test_xclaim_forwards_arguments() -> None:
    fake = FakeRawRedis()
    client = RedisStreamClient(fake)

    asyncio.run(
        client.xclaim(
            "active_streams",
            "group",
            "consumer",
            min_idle_time=0,
            message_ids=["1-0"],
        )
    )

    assert fake.xclaim_calls == [
        {
            "name": "active_streams",
            "groupname": "group",
            "consumername": "consumer",
            "min_idle_time": 0,
            "message_ids": ["1-0"],
        }
    ]
