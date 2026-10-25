# Diagrams

This folder contains the main architecture and flow diagrams for the STT system.

- [batch.mermaid](batch.mermaid) - Batch-processing flow covering client, API, Triton, LLM summarization, and storage.
- [exec-architecture.mermaid](exec-architecture.mermaid) - High-executive level architecture showing the main service layers and their data flow.
- [extensive-live.mermaid](extensive-live.mermaid) - Detailed live speech pipeline with stream API, Redis queues, inference adapter, Triton, and synchronizer.
- [simplified-live.mermaid](simplified-live.mermaid) - Compact live speech flow for quick reference of the end-to-end streaming path.
