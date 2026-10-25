# Inference Adapter Contributor Guide

## Purpose

Tracks the service boundary that now owns audio transcoding, resampling, and decoded-sample normalization removed from stream-api.

## Current Capabilities

- Preserves the existing audio manipulation code migrated out of stream-api.
- Provides a minimal service scaffold only.
- Does not yet expose runtime interfaces or orchestration.

## Follow-Ups

- Define runtime contract for consuming raw chunk events.
- Integrate moved audio manipulation code into adapter processing flow.
- Add VAD later if required by the pipeline design.
