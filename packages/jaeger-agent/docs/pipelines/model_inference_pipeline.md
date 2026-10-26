# Pipeline: Model / Inference

**What it is:** how JROS turns a model reference in config into a loaded,
warmed brain the agent decodes against — registry resolution + first-run
download, per-format engine selection (llama.cpp vs MLX), boot prewarm, and
the opt-in external-model path (LM Studio / Ollama / OpenAI / Anthropic /
Gemini). Local-first: a fresh instance never phones home.

## The flow

```
config.model.model_path  (a registry key like "gemma-4-e4b-it-q4_k_m",
   │                       or an absolute/relative path — set by the wizard)
   │
   ▼
make_client(config, layout)                       main.py:3300
   │
   ├─ config.external_model.enabled? ──yes──► ExternalModelClient       (external_model.py:166)
   │       │                                    • resolve_api_key (creds → env)   :79
   │       │                                    • connectivity_check (GET /models)  :258
   │       │                                    • reachable → return; else fall through ↓
   │       no
   │
   ▼
resolve_engine(model_path, config.runtime)        engine_registry.py:270
   • detect_format: .gguf file → "gguf"; dir → "mlx"        :38
   • runtime_selection: config.runtime.gguf_engine / mlx_engine ("auto" default)  :221
   • "auto" → default_engine_for_format (gguf→llama-cpp-python, mlx→mlx-lm;        :198
             mlx *_unified → mlx-vlm)
   │
   ▼
engine.loader(config.model, warmup=)              engine_registry.py:125-137
   │
   ├─ llama-cpp-python → LlamaCppPythonClient      main.py:3207
   │      resolve_model_path(model_cfg.model_path)  model_resolver.py:293
   │        1. absolute path → use as-is
   │        2. registry key → user cache → repo ./models/ → LM Studio cache
   │                        → download_model() from HF Hub        :424
   │        3. relative → cwd / repo models / user cache
   │      Llama(n_ctx=ctx, n_gpu_layers=gpu_layers, n_batch, n_ubatch, flash_attn)  :3237
   │
   ├─ mlx-lm  → MlxClient(model_path)              mlx_client.py:27
   └─ mlx-vlm → MlxVlmClient(model_path)           engine_registry.py:135
   │
   ▼
prewarm(client)                                   main.py:2444
   • local only (external skips: no local KV cache)              :2482
   • Pass 1 — system prompt only (~5s)                           :2495
   • Pass 2 — system prompt + full tool schemas (~60s)           :2508
             skipped when JAEGER_FAST_BOOT=1                      :2521
   • logs "agent prewarmed in Xs (system … + tools …)"           :2554
```

Deep Think swaps the resident model in place via `switch_model` (main.py:3946):
drops the old client, GCs, loads `DEFAULT_ASLEEP_MODEL`, rebuilds the agent,
re-prewarms. With an external brain active it is a no-op (keeps the same
external model).

## Key files / functions

- `make_client(config, layout, *, warmup=True)` — main.py:3300. The single
  entry: external-first (if enabled + reachable), else local engine selection.
  Falls back to local on any external error so the robot always has a brain.
- `engine_registry.resolve_engine(model_path, runtime_config)` —
  engine_registry.py:270. Honours the operator's per-format engine choice when
  set + installed, else `default_engine_for_format`. Stale/uninstalled/wrong-
  format selection silently falls through to auto (never fails boot).
- `engine_registry.detect_format` — engine_registry.py:38. `.gguf` file →
  `"gguf"`; directory → `"mlx"`; bare key → `"gguf"` (JROS default local
  format). `mlx_needs_vlm` (:67) forces `mlx-vlm` for `*_unified` model types.
- Engine registry — engine_registry.py:143. Three `EngineSpec`s:
  `llama-cpp-python` (gguf, module `llama_cpp`), `mlx-lm` (mlx text, `mlx_lm`),
  `mlx-vlm` (mlx multimodal, `mlx_vlm`). Loaders import heavy deps lazily.
  `_FORMAT_DEFAULTS` (:174): gguf→`llama-cpp-python`, mlx→`mlx-lm`.
- `model_resolver.resolve_model_path(name_or_path, *, auto_download=True)` —
  model_resolver.py:293. Resolution order: absolute path → registry key
  (`_resolve_registered`, :359) → relative path → basename-as-key fallback.
- `model_resolver._resolve_registered` — model_resolver.py:359. For a registry
  key, checks in order: user cache `<state>/models/<key>/<file>`, repo
  `./models/<file>`, LM Studio cache `~/.lmstudio/models/<hf_repo>/<file>`, then
  `download_model`.
- `model_resolver.download_model` — model_resolver.py:424. Prefers
  `huggingface_hub.hf_hub_download` (resumable); falls back to plain `urllib`
  against `huggingface.co/<repo>/resolve/main/<file>` with a text progress bar
  (`_progress_line`, :409) when the library is absent.
- `MODEL_REGISTRY` — model_resolver.py:55. Stable key → `{hf_repo, hf_file,
  size_gb, role, description}`. `DEFAULT_MODEL` / `DEFAULT_AWAKE_MODEL` =
  `gemma-4-e4b-it-q4_k_m` (:175); `DEFAULT_ASLEEP_MODEL` / `DEFAULT_CODER_MODEL`
  = `gemma-4-26b-a4b-it-qat-q4_0` (:191).
- `LlamaCppPythonClient` — main.py:3207. `kind="local"`. Loads `Llama` once with
  `n_ctx=ctx, n_gpu_layers=gpu_layers, n_batch, n_ubatch, flash_attn` (:3237);
  optional `n_threads`. Exposes `.llm` (raw Llama), `.chat()`, `.describe()`. A
  single-thread executor serializes decode.
- `MlxClient` — mlx_client.py:27. `kind="local"`. `mlx_lm.load` on a
  single-worker executor (MLX pins a GPU stream to its creating thread — load,
  warmup, and every decode share that one thread). `.chat()` renders via the
  tokenizer chat template and runs `mlx_lm.generate` once. `MlxVlmClient` is the
  multimodal sibling (mlx_vlm_client.py).
- `prewarm(client)` — main.py:2444. Two-pass KV-cache prime, idempotent,
  external-model skip. Calls `llama.create_chat_completion` directly (bypasses
  the agent loop's stale-call detector). Emits the "agent prewarmed in Xs" log.
- `switch_model(new_model, *, warmup=True)` — main.py:3946. In-place model swap
  for Deep Think; drops old client + GCs before loading (unified-memory OOM
  guard); no-op when an external brain is active.
- Boot wiring — main.py `_boot_tui_pipeline` (~:3822): resolve instance → load
  `Config` → `make_client` → `_get_agent` → `prewarm`. The full CLI boot path
  also calls `make_client` (:4425) + `prewarm` (:4431).

### External model path
- `external_model.ExternalModelClient` — external_model.py:166. `kind="external"`.
  `.chat()` routes OpenAI-compatible providers (`lmstudio`, `ollama`,
  `ollama-cloud`, `openai`, `gemini`) through the `openai` SDK; `anthropic`
  through the `anthropic` SDK. Cloud calls wrapped in `retry_call`.
- `resolve_api_key` — external_model.py:79. Order: instance credential
  (`api_key_credential`) → `api_key_env` → conventional env var
  (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / …). Keys are never written to config.
- `validate_external_provider` — external_model.py:115. Local OpenAI-compatible
  servers accept a placeholder key; true cloud providers require a real key.
- `connectivity_check` — external_model.py:258. Cheap `GET /models` for
  OpenAI-compatible providers (reachability, not output quality); a small
  generation probe for Anthropic.

## Config (core/instance/schemas.py)

- `ModelConfig` — schemas.py:73. `backend: Literal["llama_cpp_python","mlx_lm"]`
  (:87, default `llama_cpp_python`); `model_path: Path` (:88, registry key or
  path); `ctx` (:96, default 8192, range 512–131072 — the wizard writes 32768,
  setup_wizard.py:709); `gpu_layers` (:97, -1 = all); `n_batch`/`n_ubatch` (512);
  `flash_attn` (True); `threads` (None); `max_tokens` (:102, default 4096, the
  per-turn output cap); `extra_gguf_dirs`; `stall_timeout_s` (:123).
- `RuntimeConfig` — schemas.py:206. `gguf_engine` (:222) / `mlx_engine` (:226),
  both default `"auto"` — the per-format engine selection read by
  `runtime_selection`.
- `ExternalModelConfig` — schemas.py:343. `enabled` (False), `provider`
  (Literal, default `lmstudio`), `base_url` (`http://localhost:1234/v1`),
  `model` (`local-model`), `api_key_credential` (`external_model_api_key`),
  `api_key_env`, `max_tokens` (1024), `timeout_s` (60).
- `DeepThinkConfig.coder_model` — schemas.py:191, default
  `gemma-4-26b-a4b-it-qat-q4_0` (the model `switch_model` swaps in for Deep
  Think authoring).
- `Config` — schemas.py:610. Holds `model: ModelConfig` (:614),
  `external_model` (:622); `runtime` is a `RuntimeConfig` field on `Config`.

## Status

- **Verified in code:** engine selection (format detect → runtime selection →
  auto default), the three engines, GGUF resolution + HF-Hub / urllib download,
  LM Studio cache reuse, two-pass prewarm + `JAEGER_FAST_BOOT`, `switch_model`
  swap + OOM guard, external providers + key resolution + connectivity check,
  all config fields.
- **`ModelConfig.backend` is config-visible but not the dispatcher:** the
  running engine is chosen by `resolve_engine` from the model FORMAT on disk +
  `config.runtime`, not by `config.model.backend` (schemas.py:76-87 notes the
  Literal "just makes the option config-visible"; `make_client` never reads it).
</content>
</invoke>
