"""Shared fixtures for proto parity tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def rest_proto_generated_dir() -> Path:
    """Return the rest-api generated proto directory."""
    return Path(__file__).resolve().parents[2] / "proto"


@pytest.fixture
def stream_proto_generated_dir() -> Path:
    """Return the stream-api generated proto directory."""
    repo_root = Path(__file__).resolve().parents[6]
    return repo_root / "services" / "stream-api" / "src" / "stream_api" / "proto"
