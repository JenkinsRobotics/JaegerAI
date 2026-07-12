# models/

Local GGUF model weights live here. They are **not committed** — model
files are large, so `.gitignore` excludes everything in this folder
except this README.

JaegerAI resolves the model named in an instance's `config.yaml`
through the registry (`jaeger_ai/core/models/model_resolver.py`),
looking in this order:

1. `<install_root>/.jaeger_os/models/` — the operator cache (production)
2. `jaeger_ai/models/` — **this folder** (dev convenience)
3. the LM Studio cache (`~/.lmstudio/models/`)
4. a Hugging Face Hub download on first use

To run JaegerAI locally, either let it download the model on first
boot, or drop a GGUF here yourself, e.g.:

```
models/gemma-4-E4B-it-Q4_K_M.gguf
```
