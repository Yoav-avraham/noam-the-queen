# Triton Multi-Model Inference Architecture Guide

## Overview

This document explains how to design, deploy, and manage machine learning systems using NVIDIA Triton Inference Server with multiple model types including STT (Speech-to-Text), LLMs, diarization models, and future architectures.

It focuses on practical deployment patterns, configuration discovery, and system design principles for production use.

---

# 1. Core Concept

Triton Inference Server is NOT a pipeline engine.

It is a model execution server that:

- Loads models from a repository
- Serves inference requests
- Supports multiple backends

Everything beyond inference (alignment, merging, orchestration) is your responsibility.

---

# 2. Model Repository Structure

Every model follows this structure:

```
model_repository/
  model_name/
    version_number/
      model_file
    config.pbtxt
```

## Examples

### ONNX model

```
stt_model/
  1/
    model.onnx
  config.pbtxt
```

### TensorRT model

```
llm_model/
  1/
    model.plan
  config.pbtxt
```

### Python backend

```
alignment_model/
  1/
    model.py
  config.pbtxt
```

---

# 3. Supported Model Types

| Type          | Backend        | File             |
| ------------- | -------------- | ---------------- |
| ONNX          | onnxruntime    | .onnx            |
| TensorRT      | tensorrt_plan  | .plan            |
| LLM optimized | TensorRT-LLM   | engine directory |
| Python logic  | python backend | model.py         |
| Ensemble      | ensemble       | no model file    |

---

# 4. Model Identification

Triton determines model behavior using `config.pbtxt`.

## Examples

### ONNX

```
platform: "onnxruntime_onnx"
```

### TensorRT

```
platform: "tensorrt_plan"
```

### Python backend

```
backend: "python"
```

### Ensemble

```
platform: "ensemble"
```

---

# 5. Critical Rule: Config Must Match Model

Mismatch causes errors such as:

> configuration expects 1 input, model provides 59

This happens when:

- Manually defined inputs are incorrect
- Model was exported with many internal tensors

---

# 6. How to Determine Correct Config

## Step 1: Inspect Model Inputs

### ONNX

```python
import onnx

model = onnx.load("model.onnx")

for inp in model.graph.input:
    print(inp.name)
```

## Step 2: Identify Input/Output Names

Extract:

- input names
- output names
- shapes
- dtypes

---

## Step 3: Start Minimal Config

```
name: "model"
platform: "onnxruntime_onnx"
```

Let Triton auto-complete config when possible.

---

## Step 4: Only Manually Define When Necessary

Manual definition is required for:

- ensembles
- batching control
- strict validation

---

# 7. STT Models (Speech-to-Text)

## Input

- Audio waveform (float32, 16kHz)

## Output

- Tokens or transcript text

## Common models

- Whisper
- wav2vec2

## Recommendation

Use ONNX or TensorRT depending on performance needs.

---

# 8. LLM Models

## Correct options

### Option 1 (Recommended)

TensorRT-LLM

- Best performance
- Handles KV cache
- Built for generation

### Option 2

vLLM

- Easier deployment
- Good throughput

### Option 3 (Not recommended)

ONNX Runtime

- Hard to serve
- Many inputs (KV cache explosion)
- Manual generation required

---

# 9. Why ONNX LLM Export Breaks

LLMs often expose:

- input_ids
- attention_mask
- past_key_values (many tensors)

Result:

- dozens of inputs
- complex config
- difficult inference serving

---

# 10. Ensembles

Ensembles are used for:

- simple model chaining
- tensor routing

NOT for:

- alignment logic
- business logic
- LLM pipelines

---

# 11. Recommended System Architecture

```
Audio
  ↓
ASR model (Triton)
  ↓
Diarization model (Triton)
  ↓
Python alignment layer
  ↓
Speaker-tagged transcript
  ↓
LLM summarization (Triton / TensorRT-LLM)
```

---

# 12. Where Logic Should Live

| Component               | Location       |
| ----------------------- | -------------- |
| Model inference         | Triton         |
| Alignment               | Python service |
| Pipeline orchestration  | Python layer   |
| Model chaining (simple) | Ensemble       |

---

# 13. Adding New Models (Future-Proofing)

## Step 1: Identify model type

- STT
- LLM
- vision
- embedding

## Step 2: Select backend

- ONNX
- TensorRT
- Python
- TensorRT-LLM

## Step 3: Inspect model inputs automatically

## Step 4: Start with minimal config

## Step 5: Extend only if needed

---

# 14. Golden Rule

Never write `config.pbtxt` before inspecting model inputs and outputs.

---

# 15. Summary

Triton is:

- a high-performance inference server
- not a workflow engine

Your system must:

- handle logic externally
- use Triton for execution only
- choose backend per model type

---

# 16. Final Recommendation Stack

| Task              | Best Choice     |
| ----------------- | --------------- |
| STT               | ONNX / TensorRT |
| Diarization       | ONNX            |
| LLM Summarization | TensorRT-LLM    |
| Alignment         | Python service  |
| Simple pipelines  | Ensemble        |

# Triton

## Docker

```bash
docker run --rm -p8000:8000 -p8001:8001 -p8002:8002 -v $(pwd)/models:/models nvcr.io/nvidia/tritonserver:24.01-py3 tritonserver --model-repository=/models
```

This would run a docker container with the three ports `8000-8082` open which are

```markdown
HTTPService at 8000
GRPCInferenceService at 8001
Metrics Service at 8002
```

## Model repository

For documentation: [see here](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/model_repository.html)

## Model "compilation" (Onnx)

For documentation: [see here](https://docs.nvidia.com/deeplearning/tensorrt/latest/getting-started/quick-start-guide.html)

If the model needs to be converted to a format that triton suuports, i.e. `.onnx`

Before starting you need to install `transformers` and `optimum` packages.

I used: `pip install transformers "optimum[onnxruntime]"`

After downloading the model from huggingface, you should run

```bash
optimum-cli export onnx --model <hf_name_or_path_to_model> <name_of_compiled_modle> --task <choose_from_optimum-cli_list>
```

Note that at this point you can deploy the model to triton, but it's not recommended since the model isn't optimized for production usecase.

## Deploy model to production

At this point you should have a `.onnx` model compiled.

In this section the model would be converted into `.engine/.plan`.

the python package will be used here, most common is the cli method.
