# Engineering Standards

Last verified: 2026-05-29

## Purpose

Defines coding standards for all Python services in this monorepo.

## Required Python Baseline

- Use Python 3.12+ syntax.
- Add `from __future__ import annotations` at the top of Python modules.
- Use full type hints for function signatures and key class attributes.
- Prefer modern type syntax (`X | Y`, `list[str]`).

## Import Layout

Use five sections in order:

1. Future
2. Standard library
3. Third-party
4. First-party
5. Local

Keep each section alphabetized and separated by one blank line.

## Type Placement Rules

- Keep shared domain contracts in service package `src/<service_name>/types.py` files.
- Keep local wiring aliases in the module where they are used.
- Promote local aliases to `src/<service_name>/types.py` only when they are reused across module boundaries.
- Do not build aggregator type modules that import runtime modules back into `types.py`; this can create circular imports.

Examples:

- Synchronizer shared contracts belong in `services/synchronizer/src/synchronizer/types.py`.
- Stream API shared queue/session route contracts belong in `services/stream-api/src/stream_api/types.py`.

## Configuration Pattern

- Prefer one of the two approved config patterns consistently within a service:
  - Frozen dataclass config loaded via `from_env()`.
  - `pydantic_settings.BaseSettings` with `frozen=True`, explicit field constraints, and env-backed initialization.
- If `BaseSettings` uses a custom `__init__`, provide `typing.overload` signatures so explicit construction remains type-safe.
- Avoid hardcoded environment-specific values.
- Fail fast for required missing values.

## Error Handling

- No silent failures.
- Validation issues must be explicit and logged.
- gRPC protocol failures should surface clear status semantics.

## Error Contract Modules

- Keep service error mappings in service package `src/<service_name>/errors.py` files.
- Use canonical `ErrorKey` to `ErrorDefinition` mappings for runtime error translation.
- Construct typed errors using keys (for example, `InvalidAudioInput(key=ErrorKey.DECODE_INVALID_ARGUMENT)`) rather than free-form strings.

## Logging

- Define `logger = logging.getLogger(__name__)` per module.
- Use structured logging (`extra={...}`) for stream/session context.
- Avoid logging secrets or personal data.

## Code Style & Readability

- Add blank lines before and after control-flow blocks (`if`, `for`, `while`, `try`) and before `return` statements for readability.
  - **Note:** This will be enforced automatically once [ruff#18255](https://github.com/astral-sh/ruff/issues/18255) is resolved. Until then, enforce via code review.

Example:

```python
def process_value(x: int) -> str:
    if x < 0:
        logger.warning("negative value", extra={"x": x})
        return "invalid"

    result = expensive_calculation(x)

    if result > 100:
        return "high"

    return "normal"
```

## Protocol Buffers Rules

- Use `proto3`.
- Use versioned package naming (example: `stream_api.v1`).
- Never edit generated `*_pb2.py`, `*_pb2_grpc.py`, `*.pyi` files manually.
- Regenerate protobuf outputs when `.proto` changes.

## Testing Expectations

- Use `pytest`.
- Keep tests near service scope (`services/<service>/tests`).
- Cover happy paths and validation failures.
- Maintain minimum coverage target of 80% for touched service code.

## Anti-Patterns

- Cross-service imports
- Mutable runtime configuration objects
- Untyped public APIs
- Swallowed exceptions (`except: pass`)
- Hardcoded production endpoints in source code

## Related Pages

- `architecture-boundaries.md`
- `development-workflow.md`
- `services/README.md`
