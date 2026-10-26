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

In priority order: the instance credential named
`api_key_credential` → the env var named `api_key_env` → the
provider's conventional env var (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`).
Keys are never written to `config.yaml` and never logged.

## Boot behaviour and fallback

At boot, `make_client()` builds the external client and runs a tiny
live connectivity check. If the endpoint is unreachable or the key is
missing, it **prints a warning and falls back to the local model** —
the robot is never left without a brain because a cloud endpoint is
down. `/model` in the TUI shows which brain actually came up.

## Notes

- **Deep Think model-swap** (`switch_model`, the local Realtime ⇄ Coder
  swap) is a llama-cpp feature. With an external brain, Deep Think keeps
  running on that same external model — there is no local coder model
  to swap to.
- The setup wizard does not write this section; add it by hand. This
  keeps the default install local-only.
- Switching is config-driven: edit `config.yaml`, restart. There is no
  hot-swap to a cloud model mid-session (it would change billing and
  data-egress behaviour silently — a restart makes the change explicit).
