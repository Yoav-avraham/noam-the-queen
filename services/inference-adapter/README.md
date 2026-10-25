# Inference Adapter Service

## Folder Purpose

Preserves audio adaptation code that is being removed from stream-api.

## Current Scope

- Houses audio transcoding, resampling, and decoded-sample validation code.
- Exists as a service scaffold only in this phase.
- Does not yet implement runtime orchestration.

## Key Paths

- Service runtime: `src`
- Tests: `src/inference_adapter/tests`

## Documentation

- Contributor service docs: `../../docs/contributor/services/inference-adapter/README.md`
- Contributor standards: `../../docs/contributor/engineering-standards.md`
