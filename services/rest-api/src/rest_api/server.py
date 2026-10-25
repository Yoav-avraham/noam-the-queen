"""Server bootstrap for the rest API service."""

from __future__ import annotations

import logging

import uvicorn

from .app import create_app
from .config import RestApiConfig


def serve(config: RestApiConfig | None = None) -> None:
    """Configure logging and run the rest API under uvicorn.

    Args:
        config: Optional runtime configuration. Loaded from environment when omitted.
    """
    config = config or RestApiConfig.from_env()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    app = create_app(config)
    logging.getLogger(__name__).info(
        "rest api starting",
        extra={"host": config.host, "port": config.port, "stream_api": config.stream_api_target},
    )
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level="info",
        ws_max_size=config.max_upload_bytes + 1024 * 1024,
    )


def main() -> None:
    """Run the server entrypoint."""
    serve()
