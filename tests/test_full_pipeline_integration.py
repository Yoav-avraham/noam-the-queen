"""End-to-end integration test spanning every STT service over real Redis.

Verifies the entire client journey across all microservices:

    client --POST /v1/authorize--> rest-api            (issues bearer token)
    client --Socket.IO upload---->  rest-api            (token-authenticated)
    rest-api --gRPC StreamAudio--> stream-api           (audio chunks)
    stream-api --ready_audio----->  inference-adapter    (Redis stream)
    inference-adapter --triton_output--> synchronizer    (Redis stream)
    synchronizer --final_output->  stream-api            (Redis stream)
    stream-api --gRPC result---->  rest-api -> client    (transcript event)
    rest-api --summary----------->  client               (summary event)

Mock boundaries (only the external AI/storage edges are faked):
* inference-adapter: model gateways + preprocessing are replaced with a scripted
  handler standing in for the Triton inference layer.
* rest-api: vLLM summarization, Postgres store, and S3 storage are faked.
Everything in between (gRPC, Redis streams, consumer groups, transcript merge,
routing, aggregation) runs for real.

Requires Redis. Start it with ``docker compose up -d redis``.
"""

from __future__ import annotations

import os
import socket
from typing import Any
import asyncio
import logging
import contextlib

import httpx
import pytest
import uvicorn
import socketio
import redis.asyncio as redis_asyncio

from rest_api.app import create_app
from rest_api.config import RestApiConfig
from rest_api.context import AppContext
from stream_api.config import StreamApiConfig
from stream_api.server import serve as stream_api_serve
from synchronizer.server import serve as synchronizer_serve
from stt_common.contracts import ACTIVE_STREAMS_KEY, StreamName, ServiceOutput
from inference_adapter.config import DEFAULT_CONSUMER_GROUP_NAME as INFERENCE_GROUP
from stt_common.stream_manager import StreamManager
from stt_common.redis_stream_client import RedisStreamClient

logger = logging.getLogger(__name__)

REDIS_URL = "redis://localhost:6379"
SPOKEN_WORDS = ["hello", "world"]
EXPECTED_TRANSCRIPT = "hello world"  # speaker label is localized by synchronizer
EXPECTED_SUMMARY = "fake summary"


def _step(message: str) -> None:
    """Print a timestamped progress marker so the flow is visible (use ``-s``)."""
    print(f"[pipeline] {message}", flush=True)
    logger.info(message)


# --------------------------------------------------------------------------- #
# Mock inference layer (stands in for the inference-adapter's Triton gateways).
# --------------------------------------------------------------------------- #
async def _fake_inference_handler(source: ServiceOutput) -> dict[str, Any]:
    """Produce scripted word/speaker segments instead of calling Triton."""
    _step(f"inference-adapter: handling chunk for session={source.session_id} is_final={source.is_final}")
    words = [
        {"start_timestamp": float(i), "end_timestamp": float(i) + 0.5, "value": word}
        for i, word in enumerate(SPOKEN_WORDS)
    ]
    speakers = [{"start_timestamp": 0.0, "end_timestamp": float(len(SPOKEN_WORDS)), "value": "1"}]
    return {"words": words, "speakers": speakers}


# --------------------------------------------------------------------------- #
# rest-api fakes (vLLM, Postgres, S3) — only external edges are mocked.
# --------------------------------------------------------------------------- #
class _FakeSummarizationService:
    async def summarize(self, transcript: Any, *, system_prompt: str) -> Any:
        from rest_api.summary.summarization_service import SummarizationResponse

        del system_prompt
        _step("rest-api: vLLM summarization invoked (mocked)")
        return SummarizationResponse(
            data={"text": EXPECTED_SUMMARY},
            model="fake-model",
        )


class _FakeStore:
    def __init__(self) -> None:
        self.rows: dict[str, Any] = {}

    async def create_session(self, **kwargs: Any) -> Any:
        from datetime import UTC, datetime

        from rest_api.db import SessionView

        view = SessionView(
            session_id=kwargs["session_id"],
            participant_ids=tuple(kwargs["participant_ids"]),
            meeting_type=kwargs["meeting_type"],
            status=str(kwargs["status"]),
            text=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.rows[view.session_id] = view
        return view

    async def get_session(self, session_id: str) -> Any:
        return self.rows.get(session_id)

    async def update_status(self, session_id: str, status: Any) -> None:
        return None

    async def close_session(self, session_id: str, *, text: str) -> Any:
        return self.rows.get(session_id)

    async def fail_session(self, session_id: str) -> None:
        return None


class _FakeStorage:
    async def ensure_bucket(self) -> None:
        return None

    async def upload_audio(self, *, session_id: str, data: bytes, **_: Any) -> str:
        return f"sessions/{session_id}/audio/upload.bin"


class _FakePromptRepository:
    async def get(self, *, user_id: str, meeting_type: str) -> str:
        return f"prompt for {user_id}/{meeting_type}"


# --------------------------------------------------------------------------- #
# Environment setup helpers.
# --------------------------------------------------------------------------- #
def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _clean_redis(redis: redis_asyncio.Redis) -> None:
    """Drop pipeline keys/groups so each run starts from a clean slate."""
    keys = await redis.keys("ready_audio:*")
    keys += await redis.keys("triton_output:*")
    keys += await redis.keys("final_output:*")
    keys.append(ACTIVE_STREAMS_KEY)
    if keys:
        await redis.delete(*keys)


async def _build_inference_manager(client: RedisStreamClient) -> StreamManager:
    return StreamManager(
        redis_client=client,
        consumer_group_name=INFERENCE_GROUP,
        input_stream_name=StreamName.READY_AUDIO,
        service_handler=_fake_inference_handler,
    )


def _build_rest_context(stream_api_target: str) -> AppContext:
    from rest_api.pipeline import StreamAudioClient, create_channel

    config = RestApiConfig(
        stream_api_target=stream_api_target,
        database_url="postgresql+asyncpg://test:test@localhost/test",
        s3_endpoint_url="http://localhost:9000",
        token_secret="integration-secret",
        vllm_base_url="http://vllm:8000/v1",
        vllm_api_key="x",
        vllm_model="m",
        summarization_prompt_s3_key="prompts/system.txt",
        chunk_size_bytes=64 * 1024,
        status_update_interval_s=0.5,
        final_result_wait_timeout_s=25.0,
    )
    channel = create_channel(stream_api_target)
    return AppContext(
        config=config,
        store=_FakeStore(),  # type: ignore[arg-type]
        storage=_FakeStorage(),  # type: ignore[arg-type]
        prompt_repository=_FakePromptRepository(),  # type: ignore[arg-type]
        stream_client_factory=lambda: StreamAudioClient(channel),
        summarization_service=_FakeSummarizationService(),  # type: ignore[arg-type]
        channel=channel,
    )


async def _run_pipeline() -> tuple[dict[str, Any], dict[str, Any]]:
    """Boot all services, drive one client upload, return transcript+summary."""
    stream_port = _free_port()
    rest_port = _free_port()
    _step(f"allocated ports: stream-api={stream_port} rest-api={rest_port}")

    redis = redis_asyncio.from_url(REDIS_URL)
    await redis.ping()
    _step("redis: connected; cleaning pipeline keys")
    await _clean_redis(redis)

    inference_client = RedisStreamClient.from_url(REDIS_URL)
    inference_mgr = await _build_inference_manager(inference_client)

    # synchronizer runs via its real serve(); it reads REDIS_URL from the env.
    os.environ["REDIS_URL"] = REDIS_URL

    stream_config = StreamApiConfig(
        host="127.0.0.1",
        port=stream_port,
        redis_url=REDIS_URL,
        final_result_wait_timeout_s=25.0,
        final_output_poll_block_ms=50,
    )

    rest_ctx = _build_rest_context(f"127.0.0.1:{stream_port}")
    rest_app = create_app(rest_ctx.config, context=rest_ctx)
    uv_config = uvicorn.Config(rest_app, host="127.0.0.1", port=rest_port, log_level="warning")
    uv_server = uvicorn.Server(uv_config)

    tasks = [
        asyncio.create_task(stream_api_serve(stream_config)),
        asyncio.create_task(inference_mgr.run_workers()),
        asyncio.create_task(synchronizer_serve()),
        asyncio.create_task(uv_server.serve()),
    ]
    _step("started services: stream-api, inference-adapter, synchronizer, rest-api")

    transcript: dict[str, Any] = {}
    summary: dict[str, Any] = {}
    done = asyncio.Event()

    sio = socketio.AsyncClient()

    @sio.on("transcript")
    async def _on_transcript(data: dict[str, Any]) -> None:
        _step(f"client: TRANSCRIPT event text={data.get('text')!r}")
        transcript.update(data)

    @sio.on("summary")
    async def _on_summary(data: dict[str, Any]) -> None:
        _step(f"client: SUMMARY event text={data.get('text')!r}")
        summary.update(data)
        done.set()

    try:
        base = f"http://127.0.0.1:{rest_port}"
        async with httpx.AsyncClient(base_url=base) as http:
            _step("client: POST /v1/authorize/alice")
            resp = None
            for _ in range(50):  # poll until rest-api/uvicorn is bound
                try:
                    resp = await http.post("/v1/authorize/alice")
                    break
                except httpx.ConnectError:
                    await asyncio.sleep(0.2)
            assert resp is not None, "rest-api never became reachable"
            resp.raise_for_status()
            token = resp.json()["token"]
            _step("client: token received")

        await sio.connect(base, auth={"token": token, "user_id": "alice"})
        _step("client: socket.io connected; emitting upload")
        audio = b"\x10\x00" * 16000
        await sio.emit(
            "upload",
            {
                "participant_ids": ["alice"],
                "meeting_type": "screening",
                "channels": 1,
                "sample_width": 2,
                "sample_rate": 16000,
                "audio": audio,
            },
        )
        _step("client: upload emitted; waiting for transcript+summary")
        await asyncio.wait_for(done.wait(), timeout=30.0)
        _step("client: done; tearing down services")
    finally:
        with contextlib.suppress(Exception):
            await sio.disconnect()
        try:
            for g in await redis.xinfo_groups(ACTIVE_STREAMS_KEY):
                _step(
                    f"DUMP group={g['name']!r} entries-read={g.get('entries-read')} last={
                        g.get('last-delivered-id')
                    } pending={g.get('pending')} consumers={g.get('consumers')}"
                )
        except Exception as exc:  # noqa: BLE001
            _step(f"DUMP failed: {exc!r}")
        uv_server.should_exit = True
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await rest_ctx.aclose()
        await inference_client.aclose()
        await _clean_redis(redis)
        await redis.aclose()

    return transcript, summary


@pytest.mark.integration
def test_full_pipeline_transcript_and_summary() -> None:
    """Client receives both transcript and summary after the full pipeline runs."""
    transcript, summary = asyncio.run(_run_pipeline())

    assert transcript, "no transcript event received"
    assert EXPECTED_TRANSCRIPT in transcript["text"]
    assert summary.get("text") == EXPECTED_SUMMARY
