"""Shared definitions and utilities for STT services."""

from .env import read_env_int, read_env_float
from .errors import Error, ErrorDefinition

__all__ = [
    "Error",
    "ErrorDefinition",
    "read_env_int",
    "read_env_float",
]
