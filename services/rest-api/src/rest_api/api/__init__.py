"""API layer: HTTP routers, Socket.IO events, and stream orchestration."""

from __future__ import annotations

from .routes import authorization_router, register_socketio_events

__all__ = [
    "authorization_router",
    "register_socketio_events",
]
