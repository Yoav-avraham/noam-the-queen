from __future__ import annotations

from typing import cast
import asyncio
from collections.abc import AsyncIterator

import grpc

from ..proto import audio_ingest_pb2 as pb2
from ..errors import ErrorKey, get_error_definition
from .ingest_test_helpers import (
    FakeContext,
    FakeRawRedis,
    QueueEventIterator,
    audio_chunk,
    make_servicer,
    collect_responses,
)


async def next_server_event(stream: AsyncIterator[pb2.ServerEvent]) -> pb2.ServerEvent:
    """Await and return the next event from a server response stream."""
    return await anext(stream)


def test_stream_audio_emits_single_initial_ack() -> None:
    """A valid stream should emit one initial ack and write raw chunks to Redis."""

    async def run_test() -> None:
        context = FakeContext()
        redis = FakeRawRedis()
        servicer, _router, _processor = make_servicer(redis, final_output_poll_block_ms=1)
        client_chunks = QueueEventIterator()

        response_stream = servicer.StreamAudio(
            client_chunks,
            cast(grpc.aio.ServicerContext, context),  # type: ignore[arg-type]
        )
        await client_chunks.push(audio_chunk([1.0, 2.0]))
        await client_chunks.close()

        ack = await anext(response_stream)
        assert ack.WhichOneof("event") == "ack"
        assert ack.ack.session_id
        assert ack.ack.status == "ok"

        redis.add_result(
            session_id=ack.ack.session_id,
            text="done",
            is_final=True,
            redis_id="1-0",
        )

        result_event = await anext(response_stream)
        assert result_event.WhichOneof("event") == "result"
        assert result_event.result.partial_text == "done"
        trailing_events = [event async for event in response_stream]
        assert trailing_events == []

        assert redis.announcements == [ack.ack.session_id]
        assert len(redis.requests) == 1
        assert redis.requests[0].sequence_number == 1
        assert redis.requests[0].is_final is True
        assert redis.requests[0].audio == audio_chunk([1.0, 2.0]).audio

    asyncio.run(run_test())


def test_stream_audio_routes_final_result_from_redis_final_output() -> None:
    """Client stream should receive final result from Redis final_output consumer."""

    async def run_test() -> None:
        context = FakeContext()
        redis = FakeRawRedis()
        servicer, _router, _processor = make_servicer(redis, final_output_poll_block_ms=1)
        client_chunks = QueueEventIterator()

        response_stream = servicer.StreamAudio(
            client_chunks,
            cast(grpc.aio.ServicerContext, context),  # type: ignore[arg-type]
        )
        await client_chunks.push(audio_chunk([1.0, 2.0]))
        await client_chunks.close()

        ack = await anext(response_stream)
        assert ack.WhichOneof("event") == "ack"
        assert ack.ack.session_id

        redis.add_result(
            session_id=ack.ack.session_id,
            text="done from redis",
            is_final=True,
            redis_id="25-0",
        )

        result_event = await asyncio.wait_for(anext(response_stream), timeout=1.0)
        assert result_event.WhichOneof("event") == "result"
        assert result_event.result.session_id == ack.ack.session_id
        assert result_event.result.partial_text == "done from redis"
        assert result_event.result.is_final is True

        trailing_events = [event async for event in response_stream]
        assert trailing_events == []

    asyncio.run(run_test())


def test_stream_audio_emits_error_when_first_chunk_persist_fails() -> None:
    """Buffered-chunk persistence failure should emit StreamError and close the stream."""
    context = FakeContext()
    redis = FakeRawRedis(fail_chunk_persist=True)
    servicer, router, _processor = make_servicer(redis)

    responses = asyncio.run(collect_responses(servicer, [audio_chunk([1.0])], context))

    assert len(responses) == 2
    assert responses[0].WhichOneof("event") == "ack"
    assert responses[1].WhichOneof("event") == "error"
    expected_status = get_error_definition(ErrorKey.CHUNK_PERSIST_FAILED).status.name
    expected_message = get_error_definition(ErrorKey.CHUNK_PERSIST_FAILED).message
    assert expected_message is not None
    assert responses[1].error.code == expected_status
    assert expected_message == responses[1].error.message
    assert len(redis.announcements) == 1
    assert len(redis.requests) == 0
    assert router._routes == {}  # noqa: SLF001


def test_stream_audio_ignores_mismatched_client_chunk_session_id() -> None:
    """Later chunks with the wrong session_id should be ignored and not rebind the stream."""

    async def run_test() -> None:
        redis = FakeRawRedis()
        servicer, _router, _processor = make_servicer(redis, final_output_poll_block_ms=1)
        client_context = FakeContext()
        client_chunks = QueueEventIterator()

        response_stream = servicer.StreamAudio(
            client_chunks,
            cast(grpc.aio.ServicerContext, client_context),  # type: ignore[arg-type]
        )

        await client_chunks.push(audio_chunk([1.0, 2.0], session_id="session-a"))
        await client_chunks.push(audio_chunk([3.0, 4.0], session_id="session-b"))
        await client_chunks.close()

        ack = await anext(response_stream)
        assert ack.WhichOneof("event") == "ack"
        session_id = ack.ack.session_id
        assert session_id == "session-a"

        assert len(redis.requests) == 1
        assert redis.requests[0].session_id == session_id
        assert redis.requests[0].is_final is True
        assert redis.requests[0].audio == audio_chunk([1.0, 2.0], session_id="session-a").audio

        redis.add_result(
            session_id=session_id,
            text="done",
            is_final=True,
            redis_id="9-0",
        )

        result_event = await asyncio.wait_for(anext(response_stream), timeout=1.0)
        assert result_event.WhichOneof("event") == "result"
        assert result_event.result.session_id == session_id
        assert result_event.result.partial_text == "done"

        trailing_events = [event async for event in response_stream]
        assert trailing_events == []

    asyncio.run(run_test())


def test_stream_audio_waits_for_final_result_before_closing() -> None:
    """The response stream should close only after the final Redis result."""

    async def run_test() -> None:
        redis = FakeRawRedis()
        servicer, _router, _processor = make_servicer(redis, final_output_poll_block_ms=1)
        client_context = FakeContext()
        client_chunks = QueueEventIterator()

        response_stream = servicer.StreamAudio(
            client_chunks,
            cast(grpc.aio.ServicerContext, client_context),  # type: ignore[arg-type]
        )

        await client_chunks.push(audio_chunk([1.0, 2.0, 3.0, 4.0]))
        await client_chunks.close()

        ack_response = await anext(response_stream)
        assert ack_response.WhichOneof("event") == "ack"
        session_id = ack_response.ack.session_id

        final_result_task = asyncio.create_task(next_server_event(response_stream))
        await asyncio.sleep(0)
        assert not final_result_task.done()

        redis.add_result(
            session_id=session_id,
            text="final transcript",
            is_final=True,
            redis_id="25-0",
        )

        routed_response = await final_result_task
        assert routed_response.WhichOneof("event") == "result"
        assert routed_response.result.session_id == session_id
        assert routed_response.result.partial_text == "final transcript"
        assert routed_response.result.is_final is True

        trailing_events = [event async for event in response_stream]
        assert trailing_events == []

    asyncio.run(run_test())


def test_stream_audio_drops_mismatched_final_output_payload_session() -> None:
    """Redis payload with mismatched session id should be ignored."""

    async def run_test() -> None:
        redis = FakeRawRedis()
        servicer, _router, _processor = make_servicer(redis, final_output_poll_block_ms=1)
        client_context = FakeContext()
        client_chunks = QueueEventIterator()

        response_stream = servicer.StreamAudio(
            client_chunks,
            cast(grpc.aio.ServicerContext, client_context),  # type: ignore[arg-type]
        )
        await client_chunks.push(audio_chunk([1.0, 2.0, 3.0, 4.0]))
        await client_chunks.close()
        ack_response = await anext(response_stream)
        session_id = ack_response.ack.session_id

        redis.add_result(
            session_id=session_id,
            payload_session_id="other-session",
            text="ignored",
            is_final=False,
            redis_id="10-0",
        )

        final_result_task = asyncio.create_task(next_server_event(response_stream))
        await asyncio.sleep(0)
        assert not final_result_task.done()

        redis.add_result(
            session_id=session_id,
            text="accepted",
            is_final=True,
            redis_id="11-0",
        )

        routed_response = await asyncio.wait_for(final_result_task, timeout=1.0)
        assert routed_response.WhichOneof("event") == "result"
        assert routed_response.result.session_id == session_id
        assert routed_response.result.partial_text == "accepted"

        trailing_events = [event async for event in response_stream]
        assert trailing_events == []

    asyncio.run(run_test())


def test_stream_audio_empty_stream_finishes_without_events() -> None:
    """An empty client stream should finish cleanly without output events."""
    context = FakeContext()
    redis = FakeRawRedis()
    servicer, _router, _processor = make_servicer(redis)

    responses = asyncio.run(collect_responses(servicer, [], context))

    assert responses == []
    assert redis.requests == []
    assert redis.announcements == []


def test_stream_audio_times_out_waiting_for_final_result() -> None:
    """When no final synchronizer result arrives, stream emits timeout error then closes."""

    async def run_test() -> None:
        context = FakeContext()
        redis = FakeRawRedis()
        servicer, router, _processor = make_servicer(
            redis,
            final_result_wait_timeout_s=0.01,
        )
        client_chunks = QueueEventIterator()

        response_stream = servicer.StreamAudio(
            client_chunks,
            cast(grpc.aio.ServicerContext, context),  # type: ignore[arg-type]
        )
        await client_chunks.push(audio_chunk([1.0, 2.0, 3.0, 4.0]))
        await client_chunks.close()

        ack = await anext(response_stream)
        assert ack.WhichOneof("event") == "ack"

        timeout_error = await asyncio.wait_for(anext(response_stream), timeout=1.0)
        assert timeout_error.WhichOneof("event") == "error"
        expected_timeout_message = get_error_definition(ErrorKey.FINAL_RESULT_TIMEOUT).message
        expected_timeout_status = get_error_definition(ErrorKey.FINAL_RESULT_TIMEOUT).status.name
        assert timeout_error.error.code == expected_timeout_status
        assert timeout_error.error.message == expected_timeout_message

        trailing_events = [event async for event in response_stream]
        assert trailing_events == []
        assert router._routes == {}  # noqa: SLF001
        assert len(redis.announcements) == 1
        assert len(redis.requests) == 1

    asyncio.run(run_test())


def test_stream_audio_emits_error_on_chunk_persistence_timeout() -> None:
    """Chunk persistence timeout should emit DEADLINE_EXCEEDED and close stream."""

    async def run_test() -> None:
        context = FakeContext()
        redis = FakeRawRedis(chunk_persist_delay_s=0.05)
        servicer, router, _processor = make_servicer(
            redis,
            chunk_persist_timeout_s=0.01,
        )
        client_chunks = QueueEventIterator()

        response_stream = servicer.StreamAudio(
            client_chunks,
            cast(grpc.aio.ServicerContext, context),  # type: ignore[arg-type]
        )

        await client_chunks.push(audio_chunk([1.0, 2.0, 3.0, 4.0]))
        await client_chunks.close()

        ack = await anext(response_stream)
        assert ack.WhichOneof("event") == "ack"

        persist_error = await asyncio.wait_for(anext(response_stream), timeout=1.0)
        assert persist_error.WhichOneof("event") == "error"
        expected_persist_timeout_message = get_error_definition(ErrorKey.CHUNK_PERSIST_TIMEOUT).message
        expected_persist_timeout_status = get_error_definition(ErrorKey.CHUNK_PERSIST_TIMEOUT).status.name
        assert persist_error.error.code == expected_persist_timeout_status
        assert persist_error.error.message == expected_persist_timeout_message

        trailing_events = [event async for event in response_stream]
        assert trailing_events == []
        assert router._routes == {}  # noqa: SLF001

    asyncio.run(run_test())


def test_stream_audio_emits_unexpected_error_after_state_created() -> None:
    """Unexpected exceptions after session initialization must emit INTERNAL error and clean up."""

    async def run_test() -> None:
        context = FakeContext()
        redis = FakeRawRedis()
        servicer, router, processor = make_servicer(redis)
        client_chunks = QueueEventIterator()

        async def explode_during_flush(state: object, outbound_queue: object) -> bool:
            raise RuntimeError("boom during flush")

        processor._flush_final_chunk = explode_during_flush  # type: ignore[attr-defined,assignment] # noqa: SLF001

        response_stream = servicer.StreamAudio(
            client_chunks,
            cast(grpc.aio.ServicerContext, context),  # type: ignore[arg-type]
        )

        await client_chunks.push(audio_chunk([1.0, 2.0, 3.0, 4.0]))
        await client_chunks.close()

        ack = await anext(response_stream)
        assert ack.WhichOneof("event") == "ack"

        unexpected_error = await asyncio.wait_for(anext(response_stream), timeout=1.0)
        assert unexpected_error.WhichOneof("event") == "error"
        assert unexpected_error.error.code == grpc.StatusCode.INTERNAL.name
        expected_unexpected_message = get_error_definition(ErrorKey.UNEXPECTED_STREAM_FAILURE).message
        assert unexpected_error.error.message == expected_unexpected_message

        trailing_events = [event async for event in response_stream]
        assert trailing_events == []
        assert router._routes == {}  # noqa: SLF001

    asyncio.run(run_test())
