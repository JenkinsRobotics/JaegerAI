# JaegerAgent

JaegerAgent is the reusable, headless agent-brain module for JaegerOS.

It is the piece an application or robot imports when it needs a working
agent — not a loop you then have to furnish. A bare install brings its own
tool surface, skill corpus, prompt assembly, workspace sandbox and local
inference. It does not own a desktop window, installer, default character,
or complete product experience; those belong to applications such as
JaegerAI.

```bash
pip install jaeger-agent          # llama.cpp included; no server, no API key
```

```python
import jaeger_agent.tools         # ~96 tools register themselves
from jaeger_agent import JaegerAgent, get_tools
len(get_tools())                  # 96
```

## Ecosystem identity

| Field | Value |
| --- | --- |
| Repository | `jaeger-agent` |
| Python distribution | `jaeger-agent` |
| Python import | `jaeger_agent` |
| Ecosystem ID | `org.jenkinsrobotics.mind.agent` |
| Type | `module` |
| JaegerOS slot / kind | `mind` / `mind` |

JaegerAgent sits beside universal modules such as JaegerKokoroTTS and
JaegerWhisperSTT. The difference is its slot: it provides the brain rather
than one speech engine.

## What belongs here

The 0.11 extraction moved the whole agent surface out of JaegerAI, not just
the loop — roughly 43,000 lines across 178 modules:

- The agent loop, interruption, retries, loop backstop, verify gate
- OpenAI, Anthropic, Hermes XML, llama.cpp and MLX adapters, plus six model
  dialects and the drift parser local models need
- **~96 tools** — files, web, code, memory, scheduling, board, background
- **107 skills**, the v3 skill manifest, loader, curator and capability state
- Toolset scoping and the tool-bundle groupings that keep a catalogue from
  eating the context window
- Prompt assembly and context blocks
- The workspace sandbox — path resolution, read/write gates, audit trail
- Tool validation, dispatch, parallel reads, and the context guard
- The headless runtime contract (`AgentRuntime`), turn bridge, session
  routing, bus messages, and a JaegerOS `slot: mind` node

What remains in JaegerAI:

- Windowed, TUI, tray, voice, and installer experiences
- Characters, personas and the personality system
- Desktop/personal-assistant tools that need a Mac rather than an agent
- Instance management, model catalogue, plugins, and product policy
- Its own `AgentRuntime` implementation over that pipeline

A short list of seams still reaching back into the host — a memory backend,
a credential store, a venv manager — is tracked in `jaeger_agent/host.py`.
Each is bound lazily, so the package imports and runs without JaegerAI
installed; only the individual tool that needs the missing piece fails, and
it says so. That file is a ledger meant to shrink to nothing.

MCP is an optional edge adapter for exposing tools or connecting remote
clients. It is not the internal connection between JaegerAgent and a JaegerOS
device; that connection uses the JaegerOS bus, topics, tools, and capabilities.

## Install for development

```bash
git clone https://github.com/JenkinsRobotics/jaeger-agent.git
cd jaeger-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

The package declares the compatible JaegerOS version range; CI currently tests
against JaegerOS `master` while the new identity metadata settles. Pin the
tested release range before publishing a JaegerAgent release.

## Use the agent directly

The completed package can run a tool-using agent without JaegerAI:

```python
from jaeger_agent import JaegerAgent, OpenAIAdapter

agent = JaegerAgent(
    adapter=OpenAIAdapter(
        provider="openai",
        model="your-model",
        api_key="...",
    ),
    system_prompt="You are the brain for this JaegerOS project.",
)

print(agent.run_turn("Inspect the available tools and report system health."))
```

`llama-cpp-python` is a BASE dependency, not an extra, because
`provider = "llama_cpp"` is the default — a robot that pip-installs this
gets a brain that runs on its own hardware with no server and no account:

```python
from jaeger_agent.runtime import create_runtime

runtime = create_runtime(config={
    "model_path": "~/models/gemma-4-E4B-it-Q4_K_M.gguf",
    "ctx": 8192,
})
runtime.run_turn("what tools do you have?", session_key="s")
```

Extras are only for the other backends: `.[openai]` (which is a client for
the OpenAI-compatible *wire format* — LM Studio, Ollama, llama.cpp's server
and vLLM all speak it, so it covers local servers too), `.[anthropic]`, or
`.[mlx]`.

## Embed a runtime node

Implement the small runtime boundary and inject it directly:

```python
from jaeger_agent import MindNode, TurnResult


class MyRuntime:
    def run_turn(self, text: str, *, session_key: str) -> TurnResult:
        return TurnResult(text=f"You said: {text}")

    def close(self) -> None:
        pass


node = MindNode(bus=bus, runtime=MyRuntime())
```

For manifest-driven use, expose a factory with this shape:

```python
def create_runtime(*, bus, config):
    return MyRuntime()
```

Then configure `runtime_factory = "my_project.agent:create_runtime"` for the
mind node. The package resolves that factory without importing the containing
application itself.

## Extraction status

The JaegerAI `0.10` split is complete. JaegerAgent owns the reusable runtime,
loop, provider adapters, message schemas, tool execution, context management,
and mind module. JaegerAI consumes this package and retains only its application
surfaces, bundled content, product configuration, and product-specific hooks.

See [`docs/EXTRACTION.md`](docs/EXTRACTION.md) for ownership rules and the
ordered migration milestones.

## License

[Apache-2.0](LICENSE) © Jenkins Robotics
