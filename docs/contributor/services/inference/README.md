# Inference Service

Last verified: 2026-05-18
Path: `services/inference`

## Purpose

Owns inference responsibilities in the STT pipeline as implementation is introduced.

Planned focus:
- Triton server setup and runtime tuning.
- Model conversion and optimization flow.
- Ensemble pipeline composition for STT + diarization.
- Inference observability baseline.

## Current State

- Service scaffold exists.
- No production runtime contract or server behavior documented yet.

## Key Paths

- Source: `services/inference/src`
- Tests: `services/inference/src/inference/tests`

## Notes

- Add contract and runtime pages in this folder when implementation lands.
- Keep Triton deployment notes aligned with real code and operations.
- Keep this page high-level until production inference code is added.
