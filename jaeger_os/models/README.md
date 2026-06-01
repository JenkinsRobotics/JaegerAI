# models/

Local GGUF model weights live here. They are **not committed** — model
files are large, so `.gitignore` excludes everything in this folder
except this README.

Jaeger-OS resolves the model named in an instance's `config.yaml`
through the registry (`src/jaeger_os/core/model_resolver.py`), looking
in this order:

1. `~/.jaeger/models/`
2. `./models/` — **this folder**
3. a Hugging Face Hub download on first use

To run JROS locally, either let it download the model on first boot, or
drop a GGUF here yourself, e.g.:

```
models/gemma-4-26B-A4B-it-Q4_K_M.gguf
```
