"""In-memory routing between active gRPC sessions and outbound event queues."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from ..proto import audio_ingest_pb2 as pb2
from ..types import ServerEventQueue

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SessionRoute:
    """Runtime routing state for one active client session."""

    outbound_queue: ServerEventQueue
    completion_event: asyncio.Event
    final_output_task: asyncio.Task[None] | None = None


class StreamRouter:
    """Routes synchronizer results to the active client stream for each session.

    Owns the in-memory route table, duplicate-session rejection, final-result
    completion signaling, and per-session final-output task bookkeeping. It holds
    no Redis state and never parses Redis fields.
    """

    def __init__(self) -> None:
        self._routes: dict[str, SessionRoute] = {}
        self._lock = asyncio.Lock()

    async def register(self, session_id: str, outbound_queue: ServerEventQueue) -> bool:
        """Register the outbound queue for one active session.

        Returns ``False`` when a different active stream already owns the session.
        """
        async with self._lock:
            existing = self._routes.get(session_id)

            if existing is not None and existing.outbound_queue is not outbound_queue:
                logger.warning(
                    "rejecting duplicate active stream for session",
                    extra={"session_id": session_id},
                )
                return False

            self._routes[session_id] = SessionRoute(
                outbound_queue=outbound_queue,
                completion_event=asyncio.Event(),
            )
            return True

    async def unregister(self, session_id: str, outbound_queue: ServerEventQueue) -> None:
        """Remove the route mapping when an active client stream closes."""
        async with self._lock:
            existing = self._routes.get(session_id)

            if existing is not None and existing.outbound_queue is outbound_queue:
                del self._routes[session_id]

    async def route_result_event(self, result: pb2.TranscriptionResultEvent) -> bool:
        """Route one transcription result to its active session, if any.

        Returns ``True`` if delivered. A delivered final result also signals the
        session's completion event.
        """
        async with self._lock:
            route = self._routes.get(result.session_id)

        if route is None:
            logger.warning(
                "dropping transcription result for inactive session",
                extra={"session_id": result.session_id},
            )
            return False

        await route.outbound_queue.put(
            pb2.ServerEvent(
                result=pb2.ConsumerResultEvent(
                    session_id=result.session_id,
                    partial_text=result.partial_text,
                    is_final=result.is_final,
                )
            )
        )
        logger.info(
            "transcription result routed",
            extra={"session_id": result.session_id, "is_final": result.is_final},
        )

        if result.is_final:
            route.completion_event.set()

        return True

    async def wait_for_completion(self, session_id: str, timeout_s: float) -> bool:
        """Wait until the session's final result is routed, or time out.

        Returns ``False`` when the session is unknown or the timeout elapses.
        """
        route = self._routes.get(session_id)

        if route is None:
            logger.warning(
                "missing session completion event",
                extra={"session_id": session_id},
            )
            return False

        try:
            await asyncio.wait_for(route.completion_event.wait(), timeout_s)
        except TimeoutError:
            logger.warning(
                "timed out waiting for final redis result",
                extra={"session_id": session_id, "final_result_wait_timeout_s": timeout_s},
            )
            return False

        return True

    def set_final_output_task(self, session_id: str, task: asyncio.Task[None]) -> None:
        """Attach the background final-output consumer task to a session route."""
        route = self._routes.get(session_id)

        if route is not None:
            route.final_output_task = task

    async def cancel_final_output_task(self, session_id: str) -> None:
        """Cancel and await a session's final-output consumer task, if running."""
        route = self._routes.get(session_id)

        if route is None or route.final_output_task is None:
            return

        task = route.final_output_task
        route.final_output_task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def is_active(self, session_id: str) -> bool:
        """Return whether the session currently has an active route."""
        return session_id in self._routes
