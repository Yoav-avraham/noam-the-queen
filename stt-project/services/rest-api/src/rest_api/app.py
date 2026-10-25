"""FastAPI application factory and lifespan wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
import socketio
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .api import authorization_router, register_socketio_events
from .config import RestApiConfig
from .domain import RestApiError, http_status_for
from .context import AppContext, build_context

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


def create_app(
    config: RestApiConfig | None = None,
    *,
    context: AppContext | None = None,
) -> FastAPI:
    """Build the FastAPI application with Socket.IO mounted.

    Args:
        config: Runtime configuration. Loaded from the environment when omitted.
        context: Pre-built application context. When provided (e.g. in tests),
            the app uses it as-is and does not own its lifecycle; otherwise a
            production context is built at startup and disposed at shutdown.

    Returns:
        A configured FastAPI instance wrapping a Socket.IO ASGI app.
    """
    config = config or RestApiConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ctx = context or await build_context(config)
        app.state.context = ctx

        if ctx.config.token_secret_is_default:
            logger.warning(
                "REST_API_TOKEN_SECRET is using the insecure development default; "
                "set a strong secret before any non-local deployment"
            )
        await ctx.storage.ensure_bucket()

        try:
            yield
        finally:
            if context is None:
                await ctx.aclose()

    app = FastAPI(title="STT Rest API", version="0.1.0", lifespan=lifespan)

    # Allow browser clients (e.g. the local UI) served from a different origin
    # to call this API. Credentials are only allowed when explicit origins are
    # configured, since browsers reject `Access-Control-Allow-Credentials` when
    # combined with a wildcard origin.
    allow_all_origins = config.cors_allowed_origins == ("*",)
    app.add_middleware(
       CORSMiddleware,
       allow_origins=list(config.cors_allowed_origins),
       allow_credentials=not allow_all_origins,
       allow_methods=["*"],
       allow_headers=["*"]
    )

    # When a pre-built context is provided (e.g. tests), set it eagerly so the
    # app works even without ASGI lifespan events (httpx ASGITransport).
    if context is not None:
        app.state.context = context

    @app.exception_handler(RestApiError)
    async def _on_rest_error(_request: Request, exc: RestApiError) -> JSONResponse:
        return JSONResponse(
            status_code=http_status_for(exc.key),
            content={"code": str(exc.key), "message": exc.message or ""},
        )

    app.include_router(authorization_router)

    # Socket.IO server — mounted as a sub-application on the FastAPI ASGI app.
    sio = socketio.AsyncServer(
        async_mode="asgi",
        cors_allowed_origins="*",
        max_http_buffer_size=config.max_upload_bytes + 1024 * 1024,
    )
    register_socketio_events(sio, app)
    sio_app = socketio.ASGIApp(sio, other_asgi_app=app)

    # Attach sio to the FastAPI app state so tests can access it.
    app.state.sio = sio

    # Return the Socket.IO ASGI wrapper which delegates non-sio requests to FastAPI.
    return sio_app  # type: ignore[return-value]
