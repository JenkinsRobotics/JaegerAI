# JaegerAI Model Subsystem

> **Architecture Guide for New Coders & Contributors**  
> JaegerAI is built to make state-of-the-art multi-agent execution, local-first privacy, and hybrid cloud inference simple, modular, and easy to understand.

---

## 🏛️ High-Level Architecture

Instead of scattering model handling across dozens of disconnected scripts, the entire subsystem is organized into **four cohesive pillars**:

```
                              ┌─────────────────────────────────────────┐
                              │               User Prompt               │
                              └────────────────────┬────────────────────┘
                                                   │
                       ┌───────────────────────────▼───────────────────────────┐
                       │  1. ROUTING & PRIVACY GOVERNANCE (`router.py`)         │
                       │  • Privacy Classifier: Private vs Public               │
                       │  • Endpoint Discovery: Local daemon vs Container bridge│
                       │  • Session Selection: Dynamic per-turn switching       │
                       └───────────────────────────┬───────────────────────────┘
                                                   │
                 ┌─────────────────────────────────┴─────────────────────────────────┐
                 │                                                                   │
       [Private Prompts]                                                     [Public Prompts]
                 │                                                                   │
                 ▼                                                                   ▼
┌─────────────────────────────────┐                                 ┌─────────────────────────────────┐
│ Local GGUF / MLX Execution      │                                 │ Cloud / Hosted API Execution    │
│ • Zero outbound network leakage │                                 │ • High-throughput fast lanes    │
│ • In-process Apple Silicon/GGUF │                                 │ • Deep reasoning models         │
└────────────────┬────────────────┘                                 └────────────────┬────────────────┘
                 │                                                                   │
                 └─────────────────────────────────┬─────────────────────────────────┘
                                                   │
                       ┌───────────────────────────▼───────────────────────────┐
                       │  2. DISCOVERY (`discovery.py`)                        │
                       │  • Disk Scanners: LM Studio, Hugging Face, ~/.jaeger   │
                       │  • Live Server Probes: Ollama (:11434), LM Studio     │
                       └───────────────────────────┬───────────────────────────┘
                                                   │
                       ┌───────────────────────────▼───────────────────────────┐
                       │  3. RESOLUTION (`model_resolver.py`, `registry.py`)   │
                       │  • Hardware profile matching (VRAM & Apple Silicon)   │
                       │  • Engine selection: llama.cpp, mlx-lm, mlx-vlm       │
                       └───────────────────────────┬───────────────────────────┘
                                                   │
                       ┌───────────────────────────▼───────────────────────────┐
                       │  4. EXECUTION CLIENTS (`external_model.py`, `mlx`)     │
                       │  • ExternalModelClient: OpenAI, Anthropic, Ollama     │
                       │  • MlxClient & MlxVlmClient: Apple Silicon acceleration│
                       └───────────────────────────────────────────────────────┘
```

---

## 🧩 The 4 Pillars

### 1. Routing & Privacy Governance (`router.py`)
- **`SensitivityGate`**: Scans user input before generation. If sensitive keywords (passwords, tokens, credentials, private documents) are present, it **automatically routes to local on-device weights** to guarantee zero data leakage to cloud APIs.
- **`EndpointResolver`**: Dynamically discovers whether Ollama is running locally on the Mac host, inside a Docker/Lima guest container via the host bridge (`192.168.64.1:11434`), or on a LAN address.
- **`ModelRouter`**: Object-oriented coordinator for turn routing, base URL resolution, and model selection.

### 2. Unified Model Discovery (`discovery.py`)
- **`discover_all()`**: One single function that surveys the entire system:
  - Local GGUF files in Hugging Face and LM Studio caches.
  - Local Apple Silicon MLX model directories.
  - Installed models in local Ollama daemon (`/api/tags`).
  - Running models in LM Studio (`/v1/models`).
  - Remote cloud catalogs (Ollama Cloud, OpenAI, Anthropic, Gemini, xAI).
- **`discover_local_gguf_files()`**: Clean disk scanner returning typed `DiscoveredModel` dataclass entries with sizes and locations.

### 3. Model Resolution & Engine Selection (`model_resolver.py`, `engine_registry.py`)
- Resolves human-friendly model names (`gemma-4`, `qwen3.5`) to actual weight paths and configuration.
- Chooses the optimal engine (`llama_cpp_python`, `mlx_lm`, `mlx_vlm`, or external API) based on host hardware and model format.

### 4. Execution Clients (`external_model.py`, `mlx_client.py`)
- **`ExternalModelClient`**: Unified client speaking OpenAI-compatible HTTP, Anthropic, Gemini, and Ollama protocols with robust error handling and connectivity verification.
- **`MlxClient` & `MlxVlmClient`**: Apple Silicon unified memory accelerated execution for text and vision-language models.
- **`load_history()` & `record_use()`**: Tracks recently selected models per provider so UI pickers remember user preferences across restarts.

---

## 🚀 Quickstart for New Coders

### Example 1: Route a turn with automatic privacy gating
```python
from jaeger_ai.core.models import ModelRouter

# 1. Private input is automatically routed to local weights
model, provider, decision = ModelRouter.route_turn("Here is my secret API key: sk-12345")
print(decision.classification)  # -> 'private'
print(model)                    # -> 'gemma-4-26b:latest' (local)

# 2. Public query can ride cloud or fast lane
model, provider, decision = ModelRouter.route_turn("What is the capital of France?")
print(decision.classification)  # -> 'public'
```

### Example 2: Discover all available models
```python
from jaeger_ai.core.models import discover_all

models = discover_all()
print("Local GGUF models:", len(models["local_gguf"]))
print("Ollama online:", models["ollama"]["online"])
for m in models["ollama"]["models"]:
    print(f" - {m['name']} ({m.get('size_gb')} GB)")
```

### Example 3: Resolve Ollama Daemon Endpoint
```python
from jaeger_ai.core.models import EndpointResolver

# Automatically handles Mac host vs Docker container bridge
base_url = EndpointResolver.resolve_ollama(openai_compat=True)
print(base_url)  # -> e.g. 'http://127.0.0.1:11434/v1' or 'http://192.168.64.1:11434/v1'
```

---

## 📁 File Map & Backwards-Compatibility Shims

To keep the codebase clean for beginners while ensuring older modules and tests never break, redundant files have been consolidated into unified modules with backwards-compatible shims:

| Unified Module | Purpose | Backwards-Compatible Shims |
| :--- | :--- | :--- |
| [`router.py`](file:///Users/matthewjenkins/GitHub/JaegerAI/jaeger_ai/core/models/router.py) | Routing, Privacy Gate, Endpoint Resolution | `ollama_endpoint.py`, `sensitivity_gate.py`, `session_selection.py` |
| [`discovery.py`](file:///Users/matthewjenkins/GitHub/JaegerAI/jaeger_ai/core/models/discovery.py) | Local & Remote Model Discovery | `local_discovery.py`, `model_discovery.py` |
| [`external_model.py`](file:///Users/matthewjenkins/GitHub/JaegerAI/jaeger_ai/core/models/external_model.py) | HTTP Client & Provider History | `external_model_history.py` |
| [`mlx_client.py`](file:///Users/matthewjenkins/GitHub/JaegerAI/jaeger_ai/core/models/mlx_client.py) | Apple Silicon MLX Text & VLM Clients | `mlx_vlm_client.py` |
| [`__init__.py`](file:///Users/matthewjenkins/GitHub/JaegerAI/jaeger_ai/core/models/__init__.py) | Master Package Front Door | Exports all unified symbols with lazy loading |
