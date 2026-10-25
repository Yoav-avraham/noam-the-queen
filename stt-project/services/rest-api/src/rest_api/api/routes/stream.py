"""Socket.IO event handlers for uploading audio and streaming back a transcript."""

from __future__ import annotations

from uuid import uuid4
from typing import TYPE_CHECKING
import logging

import socketio
from socketio.exceptions import ConnectionRefusedError as SioConnectionRefused

from ...domain import RestApiError
from ...security import verify_session_token
from ..stream_handler import StreamSessionHandler

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def register_socketio_events(sio: socketio.AsyncServer, app: FastAPI) -> None:
    """Attach all upload-related event handlers to the Socket.IO server."""

    @sio.event
    async def connect(sid: str, environ: dict[str, object], auth: dict[str, str] | None = None) -> bool | None:
        """Authenticate on connect using the token in the auth payload."""
        context = app.state.context
        config = context.config

        if not auth or "token" not in auth or "user_id" not in auth:
            logger.info("rejected socketio connection: missing auth")
            raise SioConnectionRefused("missing auth")

        token = auth["token"]
        user_id = auth["user_id"]

        try:
            verify_session_token(
                token=token,
                secret=config.token_secret,
                algorithm=config.token_algorithm,
                expected_user_id=user_id,
            )
        except RestApiError as exc:
            logger.info("rejected socketio connection", extra={"code": str(exc.key)})
            raise SioConnectionRefused(str(exc.key)) from exc

        await sio.save_session(sid, {"user_id": user_id, "handler": None})
        logger.info("socketio client connected", extra={"sid": sid, "user_id": user_id})

    @sio.event
    async def disconnect(sid: str) -> None:
        session = await sio.get_session(sid)
        handler: StreamSessionHandler | None = session.get("handler")

        if handler is not None:
            await handler.on_disconnect()

        logger.info("socketio client disconnected", extra={"sid": sid})

    @sio.event
    async def upload(sid: str, data: dict[str, object]) -> dict[str, str]:
        """Receive audio + metadata, create a session room, and begin processing.

        Args:
            sid: Socket.IO connection ID (assigned automatically by the server
                on connect — the client does not send this manually).
            data: Event payload from the client.

        Expected payload::

            {
                "participant_ids": ["alice", "bob"],
                "meeting_type": "hr_interview",
                "channels": 1,
                "sample_width": 2,
                "sample_rate": 16000,
                "audio": <bytes>
            }

        Returns ``{"session_id": "<uuid>"}`` via Socket.IO acknowledgement.
        The client also receives transcript/status/error events on the
        session room.
        """
        context = app.state.context

        audio = data.pop("audio", None)
        if not isinstance(audio, bytes | bytearray):
            await sio.emit("error", {"code": "empty_upload", "message": "audio field is required"}, to=sid)
            return {"session_id": ""}

        session_id = str(uuid4())

        # Join a Socket.IO room named after the session so downstream events
        # (transcript, status, closed, error) are scoped to this session.
        await sio.enter_room(sid, session_id)

        session = await sio.get_session(sid)
        handler = StreamSessionHandler(
            sio,
            sid,
            context,
            session_id=session_id,
            user_id=session["user_id"],
        )
        await sio.save_session(sid, {**session, "handler": handler})

        # Save metadata + kick off processing (emits accepted, then transcript).
        await handler.on_upload(metadata=data, audio=bytes(audio))

        return {"session_id": session_id}

    @sio.event
    async def restore_session(sid: str, data: dict[str, object]) -> dict[str, object]:
        """Rejoin a session room and return accumulated state for recovery.

        Args:
            sid: Socket.IO connection ID (assigned automatically by the server
                on connect — the client does not send this manually).
            data: Event payload from the client.

        Expected payload::

            {"session_id": "<uuid>"}

        Returns the current session snapshot via Socket.IO acknowledgement so
        the client can resume where it left off after a reconnection.
        """
        context = app.state.context
        session_id = data.get("session_id")

        if not session_id or not isinstance(session_id, str):
            return {"error": "missing_session_id"}

        sio_session = await sio.get_session(sid)
        user_id: str = sio_session["user_id"]

        session_view = await context.store.get_session(session_id)
        if session_view is None:
            logger.info(
                "restore_session: session not found",
                extra={"sid": sid, "session_id": session_id},
            )
            return {"error": "session_not_found"}

        # Join the session room so the client receives any future events.
        await sio.enter_room(sid, session_id)

        logger.info(
            "client restored session",
            extra={"sid": sid, "session_id": session_id, "user_id": user_id},
        )

        return {
            "session_id": session_view.session_id,
            "status": session_view.status,
            "text": session_view.text,
            "created_at": session_view.created_at.isoformat(),
            "updated_at": session_view.updated_at.isoformat(),
        }
