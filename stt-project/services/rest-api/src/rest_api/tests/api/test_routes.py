"""Integration tests for REST and Socket.IO routes using a fake context."""

from __future__ import annotations

from typing import TYPE_CHECKING
import asyncio
from contextlib import asynccontextmanager

from httpx import AsyncClient, ASGITransport
import pytest
from fastapi import FastAPI
import uvicorn
import socketio
import socketio.exceptions

from rest_api.app import create_app
from rest_api.context import AppContext
from rest_api.pipeline import StreamFailure
from rest_api.security import issue_session_token

from ..conftest import (
    FakeStorage,
    FakeSessionStore,
    FakeStreamClient,
    FakePromptRepository,
    FakeSummarizationService,
    make_config,
    default_stream_events,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _make_context(
    store: FakeSessionStore,
    storage: FakeStorage,
    stream_client: FakeStreamClient,
    config_overrides: dict[str, object] | None = None,
) -> AppContext:
    return AppContext(
        config=make_config(**(config_overrides or {})),
        store=store,  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
        prompt_repository=FakePromptRepository(),  # type: ignore[arg-type]
        stream_client_factory=lambda: stream_client,  # type: ignore[arg-type,return-value]
        summarization_service=FakeSummarizationService(),  # type: ignore[arg-type]
    )


def _build_app(context: AppContext) -> FastAPI:
    return create_app(context.config, context=context)


@pytest.fixture
def default_context() -> AppContext:
    store = FakeSessionStore()
    storage = FakeStorage()
    stream_client = FakeStreamClient(events=default_stream_events())
    return _make_context(store, storage, stream_client)


# ---------------------------------------------------------------------------
# REST endpoint tests (these still use httpx/TestClient via FastAPI)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorize_returns_token(default_context: AppContext) -> None:
    app = _build_app(default_context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/authorize/user-1")
    assert response.status_code == 201
    body = response.json()
    assert body["token"]
    assert body["expires_at"]


# ---------------------------------------------------------------------------
# Socket.IO tests
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _serve_app(app: FastAPI) -> AsyncIterator[int]:
    """Start a uvicorn server on a random port, yield the port, then shut down."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    # Wait until the server is accepting connections.
    while not server.started:
        await asyncio.sleep(0.01)
    port: int = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield port
    finally:
        server.should_exit = True
        await task


async def _connect_sio(
    port: int,
    *,
    user_id: str = "user-1",
    token: str,
) -> tuple[socketio.AsyncClient, list[tuple[str, object]]]:
    """Create a Socket.IO client connected to the local test server."""
    received: list[tuple[str, object]] = []
    client = socketio.AsyncClient()

    async def on_accepted(data: object) -> None:
        received.append(("accepted", data))

    async def on_transcript(data: object) -> None:
        received.append(("transcript", data))

    async def on_closed(data: object) -> None:
        received.append(("closed", data))

    async def on_error(data: object) -> None:
        received.append(("error", data))

    async def on_status(data: object) -> None:
        received.append(("status", data))

    async def on_summary(data: object) -> None:
        received.append(("summary", data))

    client.on("accepted", on_accepted)
    client.on("transcript", on_transcript)
    client.on("closed", on_closed)
    client.on("error", on_error)
    client.on("status", on_status)
    client.on("summary", on_summary)

    await client.connect(
        f"http://127.0.0.1:{port}",
        socketio_path="/socket.io",
        transports=["websocket"],
        auth={"token": token, "user_id": user_id},
        wait_timeout=5,
    )
    return client, received


@pytest.mark.asyncio
async def test_socketio_rejects_invalid_token(default_context: AppContext) -> None:
    app = _build_app(default_context)
    async with _serve_app(app) as port:
        client = socketio.AsyncClient()
        with pytest.raises(socketio.exceptions.ConnectionError):
            await client.connect(
                f"http://127.0.0.1:{port}",
                socketio_path="/socket.io",
                transports=["websocket"],
                auth={"token": "bogus", "user_id": "user-1"},
                wait_timeout=5,
            )


@pytest.mark.asyncio
async def test_socketio_rejects_missing_auth(default_context: AppContext) -> None:
    app = _build_app(default_context)
    async with _serve_app(app) as port:
        client = socketio.AsyncClient()
        with pytest.raises(socketio.exceptions.ConnectionError):
            await client.connect(
                f"http://127.0.0.1:{port}",
                socketio_path="/socket.io",
                transports=["websocket"],
                wait_timeout=5,
            )


@pytest.mark.asyncio
async def test_socketio_rejects_user_mismatch(default_context: AppContext) -> None:
    app = _build_app(default_context)
    token, _ = issue_session_token(user_id="other-user", secret="test-secret", algorithm="HS256", ttl_s=60)
    async with _serve_app(app) as port:
        client = socketio.AsyncClient()
        with pytest.raises(socketio.exceptions.ConnectionError):
            await client.connect(
                f"http://127.0.0.1:{port}",
                socketio_path="/socket.io",
                transports=["websocket"],
                auth={"token": token, "user_id": "user-1"},
                wait_timeout=5,
            )


@pytest.mark.asyncio
async def test_full_socketio_upload_flow() -> None:
    store = FakeSessionStore()
    storage = FakeStorage()
    stream_client = FakeStreamClient(events=default_stream_events())
    context = _make_context(store, storage, stream_client)
    app = _build_app(context)

    async with _serve_app(app) as port:
        # Get a valid token
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
            resp = await http.post("/v1/authorize/user-1")
        token = resp.json()["token"]

        client, received = await _connect_sio(port, token=token)

        await client.emit(
            "upload",
            {
                "participant_ids": ["alice", "bob"],
                "meeting_type": "screening",
                "channels": 1,
                "sample_width": 2,
                "sample_rate": 16000,
                "audio": b"some-audio-data-bytes",
            },
        )
        await asyncio.sleep(1.0)  # let processing complete

        await client.disconnect()

    event_types = [name for name, _ in received]
    assert "accepted" in event_types
    assert "transcript" in event_types
    assert "summary" in event_types
    assert "closed" in event_types

    transcript = next(data for name, data in received if name == "transcript")
    assert isinstance(transcript, dict)
    assert "hello world" in transcript["text"]


@pytest.mark.asyncio
async def test_socketio_upstream_failure() -> None:
    store = FakeSessionStore()
    storage = FakeStorage()
    failing_client = FakeStreamClient(events=[StreamFailure(code="INTERNAL", message="boom")])
    context = _make_context(store, storage, failing_client)
    app = _build_app(context)

    async with _serve_app(app) as port:
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
            resp = await http.post("/v1/authorize/user-1")
        token = resp.json()["token"]

        client, received = await _connect_sio(port, token=token)

        await client.emit(
            "upload",
            {
                "participant_ids": ["alice", "bob"],
                "meeting_type": "screening",
                "channels": 1,
                "sample_width": 2,
                "sample_rate": 16000,
                "audio": b"audio",
            },
        )
        await asyncio.sleep(1.0)

        await client.disconnect()

    error = next((data for name, data in received if name == "error"), None)
    assert isinstance(error, dict)
    assert error["code"] == "upstream_stream_failure"
