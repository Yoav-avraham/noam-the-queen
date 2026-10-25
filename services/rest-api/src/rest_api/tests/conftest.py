"""Shared fixtures and in-memory fakes for rest API tests."""

from __future__ import annotations

from uuid import uuid4
from typing import TYPE_CHECKING
from datetime import UTC, datetime
from dataclasses import field, dataclass
from collections.abc import Sequence, AsyncIterator

import pytest

from rest_api.db import SessionView
from rest_api.config import RestApiConfig
from rest_api.domain import SessionStatus
from rest_api.context import AppContext
from rest_api.pipeline import StreamAck, StreamEvent, StreamResult
from rest_api.summary.summarization_service import SummarizationResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterable

    from rest_api.domain import AggregatedTranscript


class FakeSummarizationService:
    """Returns a fixed summary without calling any LLM."""

    async def summarize(
        self,
        transcript: AggregatedTranscript,
        *,
        system_prompt: str,
    ) -> SummarizationResponse:
        return SummarizationResponse(
            data={"text": "fake summary", "system_prompt": system_prompt},
            model="fake-model",
        )


@dataclass
class FakePromptRepository:
    """Returns tenant prompts without contacting object storage."""

    prompts: dict[tuple[str, str], str] = field(default_factory=dict)

    async def get(self, *, user_id: str, meeting_type: str) -> str:
        return self.prompts.get((user_id, meeting_type), f"prompt for {user_id}/{meeting_type}")


@dataclass
class FakeSessionStore:
    """In-memory implementation of the SessionStore protocol."""

    rows: dict[str, SessionView] = field(default_factory=dict)

    async def create_session(
        self,
        *,
        session_id: str,
        participant_ids: Sequence[str],
        meeting_type: str,
        status: SessionStatus,
    ) -> SessionView:
        now = datetime.now(UTC)
        view = SessionView(
            session_id=session_id,
            participant_ids=tuple(participant_ids),
            meeting_type=meeting_type,
            status=str(status),
            text=None,
            created_at=now,
            updated_at=now,
        )
        self.rows[session_id] = view
        return view

    async def get_session(self, session_id: str) -> SessionView | None:
        return self.rows.get(session_id)

    async def update_status(self, session_id: str, status: SessionStatus) -> None:
        self._replace(session_id, status=str(status))

    async def close_session(
        self,
        session_id: str,
        *,
        text: str,
    ) -> SessionView:
        self._replace(
            session_id,
            status=str(SessionStatus.CLOSED),
            text=text,
        )
        return self.rows[session_id]

    async def fail_session(self, session_id: str) -> None:
        self._replace(session_id, status=str(SessionStatus.FAILED))

    def _replace(self, session_id: str, **changes: object) -> None:
        from dataclasses import replace

        self.rows[session_id] = replace(self.rows[session_id], **changes)


@dataclass
class FakeStorage:
    """Records uploaded audio without contacting object storage."""

    bucket: str = "test-bucket"
    uploads: dict[str, bytes] = field(default_factory=dict)
    ensured: bool = False

    async def ensure_bucket(self) -> None:
        self.ensured = True

    async def upload_audio(
        self,
        *,
        session_id: str,
        data: bytes,
        filename: str | None = None,
        content_type: str = "application/octet-stream",
    ) -> str:
        key = f"sessions/{session_id}/audio/{filename or 'upload.bin'}"
        self.uploads[key] = data
        return key


@dataclass
class FakeStreamClient:
    """Returns a scripted sequence of stream events for one session."""

    events: list[StreamEvent]
    received: bytearray = field(default_factory=bytearray)
    channels: int | None = None
    sample_width: int | None = None
    sample_rate: int | None = None

    async def stream_audio(
        self,
        chunks: AsyncIterable[bytes],
        *,
        channels: int,
        sample_width: int,
        sample_rate: int,
    ) -> AsyncIterator[StreamEvent]:
        self.channels = channels
        self.sample_width = sample_width
        self.sample_rate = sample_rate
        async for chunk in chunks:
            self.received += chunk
        for event in self.events:
            yield event


def make_config(**overrides: object) -> RestApiConfig:
    """Build a RestApiConfig with test-friendly defaults."""
    base: dict[str, object] = {
        "stream_api_target": "localhost:50051",
        "database_url": "postgresql+asyncpg://test:test@localhost/test",
        "s3_endpoint_url": "http://localhost:9000",
        "token_secret": "test-secret",
        "status_update_interval_s": 0.01,
        "final_result_wait_timeout_s": 1.0,
        "chunk_size_bytes": 8,
        "vllm_base_url": "http://vllm:8000/v1",
        "vllm_api_key": "test-key",
        "vllm_model": "llama-3.1-8b-instruct",
    }
    base.update(overrides)
    return RestApiConfig(**base)  # type: ignore[arg-type]


def default_stream_events(session_id: str = "stream-xyz") -> list[StreamEvent]:
    """Return a typical ack + final-result event sequence."""
    return [
        StreamAck(session_id=session_id, status="ok"),
        StreamResult(
            session_id=session_id,
            text='[{"speaker": 1, "sentence": "hello world."}]',
            is_final=True,
        ),
    ]


@pytest.fixture
def fake_store() -> FakeSessionStore:
    return FakeSessionStore()


@pytest.fixture
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def app_context(fake_store: FakeSessionStore, fake_storage: FakeStorage) -> AppContext:
    """Build an AppContext wired with fakes and a default stream client."""
    config = make_config()
    client = FakeStreamClient(events=default_stream_events())
    return AppContext(
        config=config,
        store=fake_store,  # type: ignore[arg-type]
        storage=fake_storage,  # type: ignore[arg-type]
        prompt_repository=FakePromptRepository(),  # type: ignore[arg-type]
        stream_client_factory=lambda: client,  # type: ignore[arg-type,return-value]
        summarization_service=FakeSummarizationService(),  # type: ignore[arg-type]
    )


def make_session_view(**overrides: object) -> SessionView:
    """Construct a SessionView for handler/route tests."""
    base: dict[str, object] = {
        "session_id": str(uuid4()),
        "participant_ids": ("alice", "bob"),
        "meeting_type": "screening",
        "status": str(SessionStatus.CREATED),
        "text": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    base.update(overrides)
    return SessionView(**base)  # type: ignore[arg-type]
