"""HTTP routers and Socket.IO event registration for the rest API service."""

from __future__ import annotations

from .stream import register_socketio_events
from .authorization import router as authorization_router

__all__ = ["register_socketio_events", "authorization_router"]
