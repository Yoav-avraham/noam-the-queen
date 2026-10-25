---
name: STT Black Project Standards
description: System instructions for all development in the STT Black monorepo. Enforces code standards, documentation requirements, and architectural boundaries.
applyTo: "**"
---

# STT Black Project Standards & Development Guide

**This file applies to all code contributions, pull requests, and AI-assisted development in this workspace.**

## Core Principles

1. **Follow `docs/contributor/engineering-standards.md`** — This is the single source of truth for coding standards and best practices
2. **Keep documentation synchronized with code** — When code changes, update relevant docs
3. **Strict service isolation** — Services must not cross-import (enforced by `import-linter`)
4. **Type safety first** — All functions/classes require type hints; use modern Python syntax
5. **No silent failures** — Every error must be logged and visible

---

## Before Writing Code

### 1. Consult `docs/contributor/engineering-standards.md`

If you're writing:
- **A new module** → See Section 2, 13 (Python Fundamentals, New Module Checklist)
- **A new gRPC service** → See Section 4, 13 (gRPC & Proto, New gRPC Service Checklist)
- **Tests** → See Section 8 (Testing Standards)
- **Configuration** → See Section 3 (Configuration & Environment)
- **Docker** → See Section 11 (Docker & Containerization)

**Never override standards with "common practice" or "what I see elsewhere"** — the standards doc is the project's custom definition.

### 2. Understand Service Isolation

```
✓ Allowed:     stream-api ← common           (stream-api imports common)
✓ Allowed:     inference ← common            (inference imports common)
✗ Forbidden:   stream-api ← inference        (cross-service imports)
✗ Forbidden:   synchronizer ← stream-api     (cross-service imports)
```

Use **gRPC** or **message queues** for inter-service communication, not imports.

### 3. Check Architecture Enforcement

Before starting work:
```bash
import-linter lint
```

This validates all import boundaries. Violations block commits.

### 4. Environment Recovery Before Refactors

If tooling suddenly fails (for example: package not found, import-linter cannot resolve root packages, pyright cannot resolve modules), **do not change project structure first**.

Always recover the repo environment before code refactors:

```bash
# Preferred repo bootstrap (matches setup.sh)
uv sync --all-packages --group dev --no-editable --link-mode copy

# Activate venv
source .venv/bin/activate

# Run architecture check the same way pre-commit does
.venv/bin/python -m importlinter.cli
```

Only if the failure persists after environment recovery should you investigate package layout or import-path changes.

---

## During Development

### When Adding Python Code

- [ ] Include `from __future__ import annotations` at top
- [ ] All functions have type hints (use modern syntax: `str | None`, not `Optional[str]`)
- [ ] Imports organized in 5 sections (future, stdlib, third-party, first-party, local)
- [ ] Define `logger = logging.getLogger(__name__)` and use structured logging
- [ ] No hardcoded values; use config from environment or passed-in params
- [ ] Docstrings for public functions (Google style)
- [ ] Errors are never silent—use `logger.warning()` or raise exceptions

**Example to follow:**
```python
from __future__ import annotations

import logging
from dataclasses import dataclass

import grpc

from proto import audio_ingest_pb2 as pb2

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class StreamState:
    stream_id: str
    chunk_count: int = 0

    async def process(self, chunk: pb2.AudioChunk) -> None:
        if not chunk.audio:
            logger.warning("empty chunk rejected", extra={"stream_id": self.stream_id})
            raise ValueError("audio chunk cannot be empty")
        self.chunk_count += 1
```

### When Modifying Protocol Buffers (.proto)

1. Edit the `.proto` file
2. Regenerate with exact command:
   ```bash
   cd services/[SERVICE]
   python -m grpc_tools.protoc \
     -I proto \
       --python_out=src/[service_name]/proto \
       --grpc_python_out=src/[service_name]/proto \
       --pyi_out=src/[service_name]/proto \
     proto/*.proto
   ```
3. Commit both `.proto` and generated files together
4. Update tests if schema changed
5. **Update relevant docs** if protocol contract changed (see "Documentation Sync" below)

### When Creating a New Service

Follow the directory structure in `docs/contributor/engineering-standards.md`:
```
services/[service-name]/
├── proto/[domain].proto
├── src/
│   └── [service_name]/
│       ├── __init__.py
│       ├── __main__.py
│       ├── config.py (frozen dataclass with from_env())
│       ├── server.py (async bootstrap)
│       ├── servicers.py (gRPC implementation)
│       └── proto/ (generated, never edit)
├── tests/test_*.py
├── Dockerfile
└── pyproject.toml
```

Add tests immediately—80% coverage minimum.

### Code Quality Before Commit

Run these in order:

```bash
# 1. Linting & formatting
ruff check --fix services/[your-service]

# 2. Type checking
pyright services/[your-service]/src/[service_name]

# 3. Architecture validation
import-linter lint

# 4. Tests & coverage
pytest services/[your-service]/src/[service_name]/tests --cov=services/[your-service]/src/[service_name] --cov-fail-under=80
```

**All must pass** before committing. Pre-commit hooks enforce this automatically.

---

## Documentation Sync Requirements

### ⚠️ When Documentation MUST Be Updated

Update these docs **whenever code changes**:

**1. `docs/contributor/engineering-standards.md`** — Update if:
   - Adding a new architectural pattern (e.g., new config pattern, new error handling approach)
   - Changing tool versions or dependencies
   - Refining an existing standard (add to anti-patterns section)
   - Creating a new checklist (Section 13)

**2. `docs/consumer/stream-api-proto-guide.md`** — Update if:
   - Adding/changing a proto contract
   - Adding new message fields that consumers need to know about
   - Changing package naming or versioning scheme

**3. `docs/contributor/architecture-boundaries.md`** — Update if:
   - Adding a new service with different isolation rules
   - Changing import-linter constraints

**4. `README.md`** — Update if:
   - Adding new setup steps
   - Changing how services are started locally or in Docker
   - Adding new dependencies

**5. Service-specific `pyproject.toml`** — Update if:
   - Adding/upgrading dependencies affecting that service

### Do NOT Create Duplicate Documentation

If a pattern is already in `docs/contributor/engineering-standards.md`, don't create a separate doc. Link to it instead.

**Bad:**
```markdown
# Custom Configuration Method

We use frozen dataclasses for config...
```

**Good:**
```markdown
# Configuration

See [Contributor Standards](docs/contributor/engineering-standards.md)
for the standard pattern.
```

### Documentation Comments in Code

Add explanatory comments for **why** decisions were made, especially for non-obvious patterns:

**Good:**
```python
# Phase 1: Accept and validate audio; do not emit ACK messages yet.
# See docs/contributor/engineering-standards.md for forward-compatibility strategy.
if False:
    yield pb2.ServerEvent()  # Keeps signature as async generator
```

**Bad:**
```python
if False:
    yield pb2.ServerEvent()  # wtf?
```

---

## Git Workflow

### Commit Message Format (Enforced)

Use Conventional Commits:
```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:** `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

**Example:**
```
feat(stream-api): add chunk sequence validation

- Enforce monotonic sequence numbers in StreamAudio RPC
- Reject out-of-order chunks with INVALID_ARGUMENT status
- Add structured logging for rejected chunks

See docs/contributor/engineering-standards.md for validation patterns.

Closes CHAIP-18
```

### Documentation in Commit Message

If your commit touches code, mention which docs should be checked/updated:

```
feat(stream-api): add authentication header support

Allows consumers to include auth tokens in stream headers.

Docs to review/update:
- docs/consumer/stream-api-proto-guide.md (add auth example)
- docs/contributor/engineering-standards.md (if new pattern)
```

---

## Code Review Checklist for Maintainers

When reviewing PRs, verify:

- [ ] Follows patterns in `docs/contributor/engineering-standards.md`
- [ ] Type hints present on all functions/classes
- [ ] Tests added (80%+ coverage)
- [ ] Pre-commit checks pass (`ruff`, `pyright`, `import-linter`, `pytest`)
- [ ] No cross-service imports introduced
- [ ] Logs are structured (using `extra={}` dict)
- [ ] `docs/contributor/engineering-standards.md` or other docs updated if pattern/process changed
- [ ] Commit messages follow Conventional Commits format
- [ ] No debug prints, `TODO` without ticket, or `pass` exception handlers

---

## Common Issues & Solutions

### "Import 'X' could not be resolved"

**Likely cause:** Cross-service import or wrong proto reference
**Solution:**
1. Check `docs/contributor/architecture-boundaries.md`
2. Run `import-linter lint` to see violations
3. Use gRPC/message queue for cross-service communication instead

### Pyright reports "attribute is not known" on proto messages

**Likely cause:** Missing `.pyi` type stubs
**Solution:** Regenerate proto with `--pyi_out` flag:
```bash
python -m grpc_tools.protoc ... --pyi_out=src/[service_name]/proto ...
```
See `docs/contributor/engineering-standards.md` for full command.

### 80% coverage gate blocking merge

**Likely cause:** New code without tests
**Solution:**
1. Add tests to `services/[service]/src/[service_name]/tests/test_[module].py`
2. See `docs/contributor/engineering-standards.md` for testing patterns
3. Run: `pytest services/[service]/src/[service_name]/tests --cov=services/[service]/src/[service_name] --cov-fail-under=80`

### "stream already started" or validation errors during streaming

**Solution:** Review `docs/contributor/engineering-standards.md` and `docs/contributor/architecture-boundaries.md` for proper state management and validation patterns.

---

## Where to Find Answers

| Question | Answer Location |
|----------|-----------------|
| How should I structure my config? | `docs/contributor/engineering-standards.md` |
| What's the right way to handle errors? | `docs/contributor/engineering-standards.md` |
| How do I log properly? | `docs/contributor/engineering-standards.md` |
| Can service X import service Y? | `docs/contributor/architecture-boundaries.md` |
| How do I write tests? | `docs/contributor/engineering-standards.md` |
| What should I name my file? | `docs/contributor/engineering-standards.md` |
| What's wrong with my proto? | `docs/consumer/stream-api-proto-guide.md` |
| How do I start the service? | `docs/contributor/development-workflow.md` |
| Is this an anti-pattern? | `docs/contributor/engineering-standards.md` |
| What checklist should I use? | `docs/contributor/development-workflow.md` |

---

## Quick Reference: Development Commands

```bash
# Sync dependencies
uv sync

# Quality checks (all must pass)
ruff check --fix services/[service]
pyright services/[service]/src/[service_name]
import-linter lint
pytest services/[service]/src/[service_name]/tests --cov=services/[service]/src/[service_name] --cov-fail-under=80

# Proto regeneration (after editing .proto)
cd services/[service]
python -m grpc_tools.protoc -I proto --python_out=src/[service_name]/proto --grpc_python_out=src/[service_name]/proto --pyi_out=src/[service_name]/proto proto/*.proto

# Run service locally
STREAM_API_PORT=50051 uv run --package stt-stream-api python -m stream_api

# Docker compose
docker-compose up
```

---

## Questions or Conflicts?

1. **Unclear standard:** Check `docs/contributor/engineering-standards.md` again; if still unclear, open an issue
2. **Standards seem wrong:** Create a discussion; agree on change, then update `docs/contributor/engineering-standards.md`
3. **Tool is not working:** Verify pre-commit hooks installed (`pre-commit install`)
4. **Merge blocked by check:** Don't bypass with `--no-verify`; fix the code instead

---

**Last Updated:** May 2026
**Scope:** All contributors (human and AI) in STT Black workspace
**Source of Truth:** `docs/contributor/engineering-standards.md`
