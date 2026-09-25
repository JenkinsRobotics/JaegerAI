# JaegerAgent

JaegerAgent is the reusable, headless agent-brain module for JaegerOS.

It is the piece an application, service, or device imports when it needs a
working agent — not a loop you then have to furnish. A bare install brings its own
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

JaegerAgent still occupies the `mind` slot, but as of 1.2 it also ships the
verified audio/vision transport needed to reach that brain. The individual
STT, TTS, streaming, duplex, and vision nodes remain portable components.

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
- The multimodal engine: four verified audio pipelines, structured turn
  context, barge-in, streaming ASR, Kokoro speech, and image turns

What remains in JaegerAI:

- Windowed, TUI, tray, and installer experiences
- Characters, personas and the personality system
- Desktop/personal-assistant tools that need a Mac rather than an agent
- Instance management, model catalogue, plugins, and product policy
- Its own `AgentRuntime` implementation over that pipeline

A short list of seams still reaching back into the host — a memory backend,
a credential store, a venv manager — is tracked in `jaeger_agent/core/host.py`.
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

### Runtime state ownership

When an application such as JaegerAI, Mochi, or JP01 hosts JaegerAgent, the
application injects its `InstanceLayout` with `workspace.bind(layout)`. Memory,
tool files, logs, and artifacts then resolve under that one application-owned
instance. For JaegerAI that canonical location is
`~/.jaeger/instances/<name>/` (or `$JAEGER_STATE_DIR/instances/<name>/`).

A standalone agent defaults to `<state root>/agent/`, where state root resolves
`JAEGER_STATE_DIR`, then `JAEGER_HOME`, then `~/.jaeger`. Source checkouts remain
free of runtime state. An explicit `DefaultWorkspace(root)` overrides that default.

`llama-cpp-python` is a BASE dependency, not an extra, because
`provider = "llama_cpp"` is the default — an application that installs this
gets an agent that runs on its host with no server and no account:

```python
from jaeger_agent.core.runtime import create_runtime

runtime = create_runtime(config={
    "model_path": "~/models/gemma-4-E4B-it-Q4_K_M.gguf",
    "ctx": 8192,
    "tools_enabled": True,  # default: full agentic tool loop
})
runtime.run_turn("what tools do you have?", session_key="s")
```

For the low-latency chatbot lane, set `tools_enabled` to `False`. The same
AgentRuntime still owns per-session conversation history and accepts image/text
content, but it gives the model an explicit empty tool list. Turning it back on
restores the existing agentic pipeline; the default remains on.

Extras are only for the other backends: `.[openai]` (which is a client for
the OpenAI-compatible *wire format* — LM Studio, Ollama, llama.cpp's server
and vLLM all speak it, so it covers local servers too), `.[anthropic]`, or
`.[mlx]`. Install `.[multimodal]` (or the compatible `.[audio]` alias) for
plain/structured audio. Quasi/full audio modes use `.[multimodal-duplex]`,
which adds Speex acoustic echo cancellation. A bare install remains a clean,
text-agent install and does not import or install the neural audio stack.

## Use the multimodal engine

Multimodal behavior is part of JaegerAgent itself: runtime plumbing, engine,
policy, context, and Events live under `jaeger_agent/core/`, following the
same anatomy as Jaeger Agent Omni. The six capability nodes remain visible
beside `skills/`, `tools/`, and `memory/` under `jaeger_agent/nodes/`. The
engine is headless and event-driven. Typed,
spoken, and image turns share one injected runtime and therefore one
conversation memory:

```text
jaeger_agent/
├── core/       runtime, bridge, policy, context, lifecycle, configuration
├── nodes/      neural/audio/vision capability manifests and runtimes
├── tools/      symbolic actions
├── skills/     reusable procedures
├── memory/     persistent agent state
├── loop/       agent iteration and tool-dispatch mechanics
├── __main__.py single command-line entry
└── module.yaml JaegerOS mind-slot manifest
```

The package root contains no implementation facades. Import implementation
modules through `jaeger_agent.core.*`; stable public classes and functions
remain exported directly from `jaeger_agent`.

```python
from jaeger_agent import MultimodalAgent

engine = MultimodalAgent(
    runtime=my_agent_runtime,
    audio_mode="structured",  # plain | structured | quasi | full
    output_mode="dynamic",    # dynamic | speech | text | mirror
    want_vision=True,
)
engine.load()
engine.attach_image("data:image/png;base64,...")
engine.send_text("What is in this image?")
```

Run the model-free contract checks or the microphone CLI with:

```bash
python tests/test_multimodal_selftest.py
python -m jaeger_agent --audio structured --vision
python -m jaeger_agent --audio plain --vision --no-agentic-tools
python -m jaeger_agent --audio plain --output-mode speech  # Gemma benchmark parity
python -m jaeger_agent selfcheck
```

`dynamic` is the agentic default. The model selects its final channel with a
typed `[OUTPUT:TEXT]`, `[OUTPUT:SPEECH]`, `[OUTPUT:BOTH]`, or
`[OUTPUT:SILENT]` directive. JaegerAgent removes the directive and routes the
content through its own output nodes; final speech never dispatches the
external `text_to_speech` tool. The decision is made inside JaegerAgent,
so every host observes the same event metadata (`display`, `channels`, and
`source`). `speech` is the reference-compatible mode: every non-empty reply is
passed to the already-warmed Kokoro node exactly as in the imported VoiceLLM
Gemma pipeline. `text` disables post-turn TTS, while `mirror` speaks responses
to spoken input and keeps typed-input responses textual.

`engine.load()` returns only after the local Gemma adapter, Whisper, Kokoro,
vision projector, and VAD have loaded and performed their component warmups.
The warmup calls the adapter directly, so no synthetic `ready` exchange enters
AgentRuntime conversation memory. Local llama.cpp weights are also closed
explicitly during engine shutdown rather than being left to interpreter-exit
ordering.

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
