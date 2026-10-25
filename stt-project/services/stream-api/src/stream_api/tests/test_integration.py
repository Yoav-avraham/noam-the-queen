from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import grpc
import numpy as np
import pytest
import redis.asyncio as redis_asyncio

from stt_common.contracts import StreamName, ServiceOutput, WindowPayload, session_stream_key

from ..proto import audio_ingest_pb2 as pb2
from ..proto import audio_ingest_pb2_grpc as pb2_grpc
from ..config import StreamApiConfig
from ..server import serve


async def _publish_final_output_result(
    redis_client: redis_asyncio.Redis,
    *,
    session_id: str,
    text: str,
) -> str:
    """Publish one final_output result envelope for a session."""
    stream_key = session_stream_key(StreamName.FINAL_OUTPUT, session_id)
    output = ServiceOutput(
        session_id=session_id,
        sequence_id=1,
        is_final=True,
        window_payload=WindowPayload(content={"text": text}),
    )
    entry_id = await redis_client.xadd(
        name=stream_key,
        fields={"data": output.model_dump_json()},
        id="*",
    )
    return entry_id.decode("ascii") if isinstance(entry_id, bytes) else entry_id


async def _read_stream_entries(
    redis_client: redis_asyncio.Redis,
    *,
    session_id: str,
) -> list[tuple[str, dict[str, str]]]:
    """Read all persisted stream entries for a given session."""
    stream_key = session_stream_key(StreamName.READY_AUDIO, session_id)
    raw_entries = await redis_client.xrange(stream_key)
    if not raw_entries:
        return []
    entries: list[tuple[str, dict[str, str]]] = []
    for entry_id_raw, fields_raw in raw_entries:
        entry_id = entry_id_raw.decode("ascii") if isinstance(entry_id_raw, bytes) else str(entry_id_raw)
        decoded_fields: dict[str, str] = {}
        if fields_raw is None:
            entries.append((entry_id, decoded_fields))
            continue
        for key, value in fields_raw.items():
            key_str = key.decode("ascii") if isinstance(key, bytes) else str(key)
            value_str = value.decode("ascii") if isinstance(value, bytes) else str(value)
            decoded_fields[key_str] = value_str
        entries.append((entry_id, decoded_fields))
    return entries


async def _read_next_event(
    stream: AsyncIterator[pb2.ServerEvent],
    *,
    timeout_s: float = 5.0,
) -> pb2.ServerEvent:
    """Read exactly one server event with a bounded wait."""
    try:
        return await asyncio.wait_for(anext(stream), timeout=timeout_s)
    except TimeoutError as exc:
        raise AssertionError(f"Timed out after {timeout_s}s waiting for server event from StreamAudio") from exc


async def _run_integration_test() -> None:
    """Execute full flow and assert audio ingestion plus Redis persistence."""
    config = StreamApiConfig(
        host="127.0.0.1",
        port=50071,
        redis_url="redis://localhost:6379",
        final_result_wait_timeout_s=0.5,
        final_output_poll_block_ms=50,
    )

    redis_client = redis_asyncio.from_url(config.redis_url)
    try:
        await redis_client.ping()  # type: ignore[misc]
    except Exception as exc:
        await redis_client.aclose()
        raise AssertionError(
            "Redis is required for services/stream-api/src/stream_api/tests/test_integration.py, "
            f"but connection failed for {config.redis_url}. "
            "Start Redis and rerun the test. Example: 'docker compose up -d redis'."
        ) from exc

    server_task = asyncio.create_task(serve(config))
    await asyncio.sleep(0.7)

    try:
        async with grpc.aio.insecure_channel(f"{config.host}:{config.port}") as channel:
            stub = pb2_grpc.AudioIngestServiceStub(channel)
            samples = np.arange(16000, dtype=np.float16)

            async def request_generator() -> AsyncIterator[pb2.AudioChunk]:
                yield pb2.AudioChunk(audio=samples.tobytes())

            call = stub.StreamAudio(request_generator())
            event_stream = call.__aiter__()

            ack = await _read_next_event(event_stream)
            assert ack.WhichOneof("event") == "ack"
            session_id = ack.ack.session_id
            assert session_id

            entry_id = await _publish_final_output_result(
                redis_client,
                session_id=session_id,
                text="Hello from session",
            )
            assert entry_id

            # After the ack the server routes the final transcription result, then closes.
            result_event = await _read_next_event(event_stream)
            assert result_event.WhichOneof("event") == "result"
            assert result_event.result.session_id == session_id
            assert result_event.result.is_final is True

            # Stream must close after the final result.
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(anext(event_stream), timeout=2.0)

            entries = await _read_stream_entries(redis_client, session_id=session_id)
            assert len(entries) == 1

            final_entry_id, final_fields = entries[0]
            assert final_entry_id
            assert set(final_fields) == {"data"}
            final_output = ServiceOutput.model_validate_json(final_fields["data"])
            assert final_output.session_id == session_id
            assert final_output.sequence_id == 1
            assert final_output.is_final is True
            assert "raw_bytes" in final_output.window_payload.content
            assert isinstance(final_output.window_payload.content["raw_bytes"], str)

            await redis_client.delete(session_stream_key(StreamName.READY_AUDIO, session_id))
            await redis_client.delete(session_stream_key(StreamName.FINAL_OUTPUT, session_id))
    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
        await redis_client.aclose()


@pytest.mark.integration
def test_integration() -> None:
    """Integration test: Redis persistence and audio ingestion lifecycle."""
    asyncio.run(_run_integration_test())
