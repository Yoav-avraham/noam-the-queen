from __future__ import annotations

from typing import Any
import asyncio
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from synchronizer import server
from synchronizer.config import DEFAULT_CONSUMER_GROUP_NAME, SynchronizerConfig
from stt_common.contracts import StreamName, ServiceOutput, WindowPayload


class _FakeRedisClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@dataclass(slots=True)
class _FakeManager:
    kwargs: dict[str, Any]
    check_calls: int = 0
    run_calls: int = 0

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.check_calls = 0
        self.run_calls = 0

    async def check_redis_connection(self) -> None:
        self.check_calls += 1

    async def run_workers(self) -> None:
        self.run_calls += 1


def test_serve_composes_stream_manager_and_merger(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_manager: _FakeManager | None = None
    fake_redis_client = _FakeRedisClient()
    captured: dict[str, Any] = {}

    def fake_stream_manager(**kwargs: Any) -> _FakeManager:
        nonlocal fake_manager
        fake_manager = _FakeManager(**kwargs)
        return fake_manager

    def fake_from_url(redis_url: str) -> _FakeRedisClient:
        captured["redis_url"] = redis_url
        return fake_redis_client

    monkeypatch.setattr(server, "configure_process", lambda: None)
    monkeypatch.setattr(server, "StreamManager", fake_stream_manager)
    monkeypatch.setattr(server.RedisStreamClient, "from_url", fake_from_url)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    asyncio.run(server.serve())

    assert fake_manager is not None
    assert captured["redis_url"] == "redis://localhost:6379/0"
    assert fake_manager.kwargs["redis_client"] is fake_redis_client
    assert fake_redis_client.closed is True
    assert fake_manager.kwargs["consumer_group_name"] == DEFAULT_CONSUMER_GROUP_NAME
    assert fake_manager.kwargs["input_stream_name"] == StreamName.TRITON_OUTPUT
    assert "output_stream_name" not in fake_manager.kwargs
    assert fake_manager.check_calls == 1
    assert fake_manager.run_calls == 1

    handler = fake_manager.kwargs["service_handler"]
    payload = ServiceOutput(
        session_id="session-1",
        sequence_id=7,
        is_final=False,
        window_payload=WindowPayload(
            content={
                "speakers": [
                    {
                        "start_timestamp": 0.0,
                        "end_timestamp": 0.0,
                        "value": "1",
                    }
                ],
                "words": [
                    {
                        "start_timestamp": 0.1,
                        "end_timestamp": 0.1,
                        "value": "hello",
                    }
                ],
            },
            locale="en",
        ),
    )

    result = asyncio.run(handler(payload))
    import json

    assert result == {"text": json.dumps([{"speaker": "1", "sentence": "hello"}])}


def test_settings_init_requires_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)

    with pytest.raises(ValidationError):
        SynchronizerConfig()


def test_settings_init_reads_consumer_group_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SYNCHRONIZER_CONSUMER_GROUP_NAME", "custom-sync-group")

    config = SynchronizerConfig()

    assert config.redis_url == "redis://localhost:6379/0"
    assert config.consumer_group_name == "custom-sync-group"
