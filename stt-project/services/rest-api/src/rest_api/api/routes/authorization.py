"""REST routes for session lifecycle management."""

from __future__ import annotations

from typing import Annotated
import logging
from datetime import datetime

from fastapi import Path, Depends, APIRouter, status
from pydantic import BaseModel

from ...config import RestApiConfig
from ...context import get_config
from ...security import issue_session_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["sessions"])

ConfigDep = Annotated[RestApiConfig, Depends(get_config)]


class AuthorizeConnectionResponse(BaseModel):
    """Response body returned after authorizing a connection."""

    token: str
    expires_at: datetime


@router.post(
    "/authorize/{user_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Issue a streaming token",
)
async def authorize_connection(
    user_id: Annotated[str, Path()],
    config: ConfigDep,
) -> AuthorizeConnectionResponse:
    logger.info(f"config: {config.token_secret} {config.token_algorithm} {config.token_ttl_s} {user_id}")
    token, expires_at = issue_session_token(
        secret=config.token_secret,
        algorithm=config.token_algorithm,
        ttl_s=config.token_ttl_s,
        user_id=user_id,
    )

    logger.info("issued streaming token", extra={"user_id": user_id})

    return AuthorizeConnectionResponse(token=token, expires_at=expires_at)
