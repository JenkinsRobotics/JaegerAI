# External-model pipeline

Jaeger-OS is **local-first**. The default brain is the in-process
llama-cpp model (Gemma 4 26B-A4B). Nothing in a fresh install phones
home.

The external-model pipeline is the **opt-in** alternative: run the
agent on a different brain without changing any agent code. Three
providers are supported:

| Provider    | What it is                                   | On-device? |
|-------------|----------------------------------------------|------------|
| `lmstudio`  | A local [LM Studio](https://lmstudio.ai) server (OpenAI-compatible HTTP) | yes |
| `openai`    | Any OpenAI-compatible cloud or self-hosted endpoint | no |
| `anthropic` | Claude via the Anthropic API                 | no |

The agent loop is identical on every brain — tools, skills, memory,
Deep Think, the benchmark suite all work the same. External models emit
native structured tool calls, so the llama-cpp drift parser is simply
not used.

## Enabling it

Add an `external_model:` block to the instance's `config.yaml`. It is
absent by default (which means: disabled, local brain).

### LM Studio (local, recommended for a bigger local model)

1. Install LM Studio, load a model, start its server (default
   `http://localhost:1234`).
2. In `config.yaml`:

   ```yaml
   external_model:
     enabled: true
     provider: lmstudio
     base_url: http://localhost:1234/v1
     model: <the model id LM Studio shows>
   ```

No API key is needed for a local LM Studio server.

### Claude (cloud)

1. Store the API key as an instance credential (the sanctioned secret
   path — never put it in `config.yaml`):

   ```
   <instance>/credentials/external_model_api_key      # mode 0600
   ```

   or export `ANTHROPIC_API_KEY` in the environment.

2. In `config.yaml`:

   ```yaml
   external_model:
     enabled: true
     provider: anthropic
     model: claude-opus-4-7
     api_key_credential: external_model_api_key
   ```

### OpenAI-compatible cloud

```yaml
external_model:
  enabled: true
  provider: openai
  base_url: https://api.openai.com/v1
  model: gpt-4o
  api_key_credential: external_model_api_key
```

## How keys are resolved

In priority order:

1. the instance credential named `api_key_credential`
2. the provider's standard credential names — `ollama_cloud_api_key`,
   `openai_api_key`, `anthropic_api_key`, `gemini_api_key`,
   `xai_api_key`, … (each provider also accepts its own aliases, e.g.
   `google_api_key` for Gemini, `grok_api_key` for xAI)
3. the generic `external_model_api_key` credential
4. the env var named `api_key_env`
5. the provider's conventional env vars — `OPENAI_API_KEY`,
   `OLLAMA_API_KEY` / `OLLAMA_CLOUD_API_KEY`, `ANTHROPIC_API_KEY`,
   `GEMINI_API_KEY` / `GOOGLE_API_KEY`, `XAI_API_KEY` / `GROK_API_KEY`

Keys are never written to `config.yaml` and never logged.

## Boot behaviour — the selected model serves, or nothing does

At boot, `make_client()` builds the external client and runs a cheap
`GET /models` connectivity check. If the endpoint is unreachable or the
key is missing, it **raises `ExternalModelSelectionError`** naming the
provider, the model, the failure, and the fixes that apply.

It does **not** load the local GGUF instead. Selecting Qwen on Ollama
Cloud and mistyping the key used to allocate ~15 GB of local weights and
answer every turn from a model the operator never chose, with nothing on
screen to say so. A selection we cannot honour is now an error, not a
substitution.

`/model use …` in the TUI preflights the same check *before* it writes
`config.yaml` and reboots, so a selection that can't serve leaves the
current brain running and prints what to fix.

Set `JAEGER_ALLOW_LOCAL_FALLBACK=1` to restore the old degrade-to-local
behaviour for unattended deployments that would rather answer from the
wrong model than not boot. It is off by default, and the fallback
announces itself on stdout and in `/model`.

## Notes

- **Switching away from a local brain frees its VRAM.** Every local
  client (`LlamaCppPythonClient`, `MlxClient`, `MlxVlmClient`) exposes
  `unload()`, and the model swap, the instance switch, and `boot_for_tui`'s
  cleanup all call it. On Apple Silicon those weights are GPU memory: when
  the next brain is an HTTP endpoint there is no second load to force the
  old one out, so a local→cloud switch used to leave 5–17 GB resident for
  the rest of the session. `ExternalModelClient.unload()` is a no-op, so
  call sites never need to ask what they're holding.
- **Deep Think model-swap** (`switch_model`, the local Realtime ⇄ Coder
  swap) is a llama-cpp feature. With an external brain, Deep Think keeps
  running on that same external model — there is no local coder model
  to swap to.
- The setup wizard does not write this section; add it by hand. This
  keeps the default install local-only.
- Switching is config-driven: edit `config.yaml`, restart. There is no
  hot-swap to a cloud model mid-session (it would change billing and
  data-egress behaviour silently — a restart makes the change explicit).
