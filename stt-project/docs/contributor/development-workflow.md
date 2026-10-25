# Development Workflow

Last verified: 2026-05-29

## Purpose

Defines the expected local workflow for coding, validation, and documentation updates.

## Setup

```bash
bash ./setup.sh
source .venv/bin/activate
```

Use WSL-based workflow for this repository.

Workspace note:
- Root `pyproject.toml` must declare workspace package sources under `[tool.uv.sources]`.
- Current required mapping includes `stt-common = { workspace = true }`.

## Quality Checks

Run relevant checks for touched services before commit:

```bash
ruff check --fix services/<service>
pyright services/<service>/src/<service_name>
import-linter lint
uv run -- pytest services/<service>/src/<service_name>/tests --cov=services/<service>/src/<service_name> --cov-fail-under=80
```

Pytest collection note:
- This monorepo uses `--import-mode=importlib` to avoid `src.tests` package-name collisions across services.
- Root `pyproject.toml` includes `pythonpath = [".", "common/src"]` so service-qualified imports resolve in tests.

## Integration Test Prerequisite

If integration tests depend on Redis, start it first:

```bash
docker compose up -d redis
```

## Proto Change Workflow

When a `.proto` contract changes:
1. Update the source `.proto`.
2. Regenerate Python outputs and `.pyi` stubs.
3. Commit both source and generated files.
4. Update impacted consumer and contributor docs.

## Commit Style

Use Conventional Commits:

```text
<type>(<scope>): <subject>
```

Examples of `type`: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.

## Documentation Trigger Checklist

Update docs whenever you change:
- Contract shape or stream behavior
- Server-side chunking or audio normalization behavior
- Runtime commands or environment variables
- Service boundaries/import policies
- Contributor standards or quality gates

## Quick References

- Standards: `engineering-standards.md`
- Boundaries: `architecture-boundaries.md`
- Service pages: `services/README.md`
