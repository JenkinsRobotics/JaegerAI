# core/models — model resolution

**This folder is code.** It decides which model a turn runs on, and finds the
file or endpoint behind a model name.

Not to be confused with **`jaeger_ai/models/`**, which holds downloaded GGUF
weight *files* and no code. Two folders named "models" is a known wart; see the
note in that folder's README.

There are 25 modules here. These are the ones you are most likely to want:

| File | What it does |
| :--- | :--- |
| `model_resolver.py` | Turns a model name into a real path or endpoint, searching the operator cache, the in-repo dev slot, LM Studio, then Hugging Face. |
| `discovery.py`, `local_discovery.py` | Lists which models are actually available on this machine. |
| `router.py` | Picks which model handles a given turn. |
| `ollama_context.py` | Works out the real context window a served Ollama model will accept. |
| `llm_client.py`, `mlx_client.py` | Talking to a running model. |
| `sensitivity_gate.py` | Keeps sensitive prompts off remote models. |

**Check it works:** `jaeger models list` shows what was discovered, and the
resolver's search order is documented at the top of `model_resolver.py`.
