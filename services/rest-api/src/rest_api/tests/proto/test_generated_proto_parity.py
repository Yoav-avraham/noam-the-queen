"""Ensure vendored generated proto files stay aligned with stream-api."""

from __future__ import annotations

import ast
import difflib
from pathlib import Path

import pytest

_GENERATED_PROTO_FILES = (
    "audio_ingest_pb2.py",
    "audio_ingest_pb2.pyi",
    "audio_ingest_pb2_grpc.py",
)


def _diff_text(
    filename: str,
    expected: str,
    actual: str,
    expected_path: Path,
    actual_path: Path,
) -> None:
    diff_lines = list(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile=str(expected_path),
            tofile=str(actual_path),
            lineterm="",
        )
    )
    max_diff_lines = 200
    truncated_suffix = ""
    if len(diff_lines) > max_diff_lines:
        truncated_suffix = f"\n\n... diff truncated ({len(diff_lines) - max_diff_lines} more lines)."
        diff_lines = diff_lines[:max_diff_lines]

    pytest.fail(
        f"Generated proto file out of sync: {filename}. "
        "Regenerate from matching proto contracts in both services.\n\n"
        "Unified diff:\n" + "\n".join(diff_lines) + truncated_suffix
    )


def _strip_docstrings(node: ast.AST) -> ast.AST:
    for child in ast.walk(node):
        body = getattr(child, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first_stmt = body[0]
        if not isinstance(first_stmt, ast.Expr):
            continue
        value = first_stmt.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            del body[0]
    return node


def _normalize_python_source(source: str) -> str:
    tree = ast.parse(source)
    normalized = _strip_docstrings(tree)
    return ast.unparse(normalized)


def _assert_python_sources_match_semantically(
    filename: str,
    expected_content: str,
    actual_content: str,
    expected_path: Path,
    actual_path: Path,
) -> None:
    expected_normalized = _normalize_python_source(expected_content)
    actual_normalized = _normalize_python_source(actual_content)
    if expected_normalized != actual_normalized:
        _diff_text(filename, expected_normalized, actual_normalized, expected_path, actual_path)


@pytest.mark.parametrize("filename", _GENERATED_PROTO_FILES)
def test_generated_proto_files_match_stream_api(
    filename: str,
    rest_proto_generated_dir: Path,
    stream_proto_generated_dir: Path,
) -> None:
    rest_file = rest_proto_generated_dir / filename
    stream_file = stream_proto_generated_dir / filename

    assert rest_file.exists(), f"Missing rest-api generated file: {rest_file}"
    assert stream_file.exists(), f"Missing stream-api generated file: {stream_file}"

    rest_content = rest_file.read_text(encoding="utf-8")
    stream_content = stream_file.read_text(encoding="utf-8")

    if filename == "audio_ingest_pb2_grpc.py":
        _assert_python_sources_match_semantically(
            filename,
            stream_content,
            rest_content,
            stream_file,
            rest_file,
        )
        return

    if rest_content != stream_content:
        _diff_text(filename, stream_content, rest_content, stream_file, rest_file)
