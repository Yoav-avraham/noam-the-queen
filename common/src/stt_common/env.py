"""Shared helpers for reading and validating environment variables."""

from __future__ import annotations

import os


def read_env_int(var_name: str, default: int) -> int:
    """Read and parse an integer environment variable with validation."""
    raw_value = os.getenv(var_name)
    if raw_value is None:
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{var_name} must be an integer, got: {raw_value!r}") from exc


def read_env_float(var_name: str, default: float) -> float:
    """Read and parse a float environment variable with validation."""
    raw_value = os.getenv(var_name)
    if raw_value is None:
        return default

    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{var_name} must be a float, got: {raw_value!r}") from exc
