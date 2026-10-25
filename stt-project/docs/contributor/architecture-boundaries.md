# Architecture Boundaries

Last verified: 2026-05-18

## Purpose

Defines service isolation and import boundaries for the monorepo.

## Services

- `services/stream-api`
- `services/inference`
- `services/inference-adapter`
- `services/synchronizer`
- `services/rest-api`

Shared package:
- `common` (import path: `stt_common`)

## Boundary Rules

1. Services must not import from other services.
2. Shared code belongs in `common` only when used by at least two services.
3. Service-specific runtime logic must stay inside the owning service.
4. Inter-service communication should use explicit interfaces (gRPC/queue), not Python imports.

## Naming Mapping

- stream-api package: `stream_api`
- inference package: `inference`
- inference-adapter package: `inference_adapter`
- synchronizer package: `synchronizer`
- rest-api package: `rest_api`
- shared package: `stt_common`

## Enforcement

- Import-linter config file: `.importlinter`
- Manual check command:

```bash
uv run python -m importlinter.cli
```

- This check should pass before merge.
