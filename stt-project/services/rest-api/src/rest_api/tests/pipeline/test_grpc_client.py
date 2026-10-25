"""Tests for the stream-api gRPC client event conversion."""

from __future__ import annotations

import pytest

from rest_api.proto import audio_ingest_pb2 as pb2
from rest_api.pipeline.grpc_client import (
    StreamAck,
    StreamResult,
    StreamFailure,
    _convert_event,
)


def test_convert_ack_event() -> None:
    event = pb2.ServerEvent(ack=pb2.StreamAck(session_id="s1", status="ok"))
    result = _convert_event(event)
    assert result == StreamAck(session_id="s1", status="ok")


def test_convert_result_event() -> None:
    event = pb2.ServerEvent(
        result=pb2.ConsumerResultEvent(
            session_id="s1",
            partial_text="hello",
            is_final=True,
        )
    )
    result = _convert_event(event)
    assert isinstance(result, StreamResult)
    assert result.text == "hello"
    assert result.is_final is True


def test_convert_error_event() -> None:
    event = pb2.ServerEvent(error=pb2.StreamError(code="DEADLINE_EXCEEDED", message="timeout"))
    result = _convert_event(event)
    assert result == StreamFailure(code="DEADLINE_EXCEEDED", message="timeout")


def test_convert_unset_event_returns_none() -> None:
    assert _convert_event(pb2.ServerEvent()) is None


@pytest.mark.asyncio
async def test_stream_audio_yields_events_from_stub() -> None:
    from collections.abc import AsyncIterator

    from rest_api.pipeline.grpc_client import StreamAudioClient

    class _FakeCall:
        def __aiter__(self) -> AsyncIterator[pb2.ServerEvent]:
            async def _gen() -> AsyncIterator[pb2.ServerEvent]:
                yield pb2.ServerEvent(ack=pb2.StreamAck(session_id="s1", status="ok"))

            return _gen()

    class _FakeStub:
        def __init__(self, _channel: object) -> None: ...

        def StreamAudio(self, request_iter: AsyncIterator[pb2.AudioChunk]) -> _FakeCall:
            self._request_iter = request_iter
            return _FakeCall()

    client = StreamAudioClient.__new__(StreamAudioClient)
    client._stub = _FakeStub(None)  # type: ignore[attr-defined]

    async def _chunks() -> AsyncIterator[bytes]:
        yield b"data"

    events = [
        event
        async for event in client.stream_audio(
            _chunks(),
            channels=1,
            sample_width=2,
            sample_rate=16000,
        )
    ]
    assert events == [StreamAck(session_id="s1", status="ok")]


@pytest.mark.asyncio
async def test_stream_audio_sets_audio_format_on_each_chunk() -> None:
    from collections.abc import AsyncIterator

    from rest_api.pipeline.grpc_client import StreamAudioClient

    sent: list[pb2.AudioChunk] = []

    class _FakeCall:
        def __init__(self, request_iter: AsyncIterator[pb2.AudioChunk]) -> None:
            self._request_iter = request_iter

        def __aiter__(self) -> AsyncIterator[pb2.ServerEvent]:
            async def _gen() -> AsyncIterator[pb2.ServerEvent]:
                async for chunk in self._request_iter:
                    sent.append(chunk)
                yield pb2.ServerEvent(ack=pb2.StreamAck(session_id="s1", status="ok"))

            return _gen()

    class _FakeStub:
        def __init__(self, _channel: object) -> None: ...

        def StreamAudio(self, request_iter: AsyncIterator[pb2.AudioChunk]) -> _FakeCall:
            return _FakeCall(request_iter)

    client = StreamAudioClient.__new__(StreamAudioClient)
    client._stub = _FakeStub(None)  # type: ignore[attr-defined]

    async def _chunks() -> AsyncIterator[bytes]:
        yield b"a"
        yield b"b"

    _ = [
        event
        async for event in client.stream_audio(
            _chunks(),
            channels=2,
            sample_width=4,
            sample_rate=44100,
        )
    ]

    assert [c.audio for c in sent] == [b"a", b"b"]
    assert all((c.channels, c.sample_width, c.sample_rate) == (2, 4, 44100) for c in sent)
