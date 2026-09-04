# JaegerAI Multimodal face

This PySide6 surface is a pump and renderer over `jaeger_agent`.
JaegerAI owns the pixels and device preview; jaeger-agent owns endpointing,
wake matching, structured context, guards, AgentRuntime/tool calls, TTS, and
barge policy.

Run the read-only preflight and model/audio-free worker test:

```bash
python -m jaeger_ai.interfaces.pyside6.multimodal --check
python -m jaeger_ai.interfaces.pyside6.multimodal --selftest
```

The normal Jaeger AI app exposes the face beside its Chat and Avatar buttons.
It connects over a private local socket to the already-running bridge and
borrows that exact Gemma/JaegerAgent runtime. Opening or closing the window
does not stop, reload, or replace the model, memory, tools, or agent loop.
Camera/microphone capture and duplex audio mechanics remain face adapters;
their committed text/image turns enter the same agent brain as every other
interface. The Multimodal conversation keeps its own session key. The
composer's **Mode: Agentic** button flips to **Mode: Chatbot** at any time.
Agentic is the default. Chatbot mode uses the same
loaded Gemma model as a tool-free chatbot with an isolated conversation
transcript and the compact multimodal prompt. This does not alter JaegerAI's
normal agentic pipeline; it only changes which lane handles the next turn.
Agentic mode uses JaegerAgent's `dynamic` output policy: the model prefixes its
single final answer with `[OUTPUT:TEXT]`, `[OUTPUT:SPEECH]`, `[OUTPUT:BOTH]`,
or `[OUTPUT:SILENT]`. JaegerAgent strips that directive and routes its own
output nodes; no final-response TTS tool call is dispatched. Chatbot mode uses the
reference-compatible `speech` policy, where every non-empty Gemma reply is
sent through Kokoro. The TELEMETRY and Agentic Workspace panels show the
resolved output channels for every turn, including `SILENT`.

The right-hand **Agentic Workspace** is a passive view over JaegerAgent's event
bus. It shows safe high-level reasoning/activity summaries, the ordered tool
chain, redacted bounded tool-result previews, returned file/artifact paths,
per-tool time, total task time, agent/model time, and reply latency. It never
changes tool execution and does not expose private token-level chain-of-thought.

For the CLI-only unstructured pipeline:

```bash
python -m jaeger_ai.interfaces.pyside6.multimodal --audio plain
```

That command attaches to a running Jaeger AI instance. An isolated second
runtime is available only when explicitly requested for development or the
reference benchmark:

```bash
python -m jaeger_ai.interfaces.pyside6.multimodal --standalone
```

## Live smoke checklist

- Open in the default Agentic **Half-Duplex** mode, say “Hey Jaeger” plus a request, and
  confirm the chosen `TEXT`, `SPEECH`, `TEXT+SPEECH`, or `SILENT` route appears.
- Switch to Chatbot mode and confirm every non-empty reply appears and is spoken,
  preserving the Gemma multimodal reference behavior.
- Switch to **Quasi Full-Duplex**, talk over a reply, and confirm playback cuts
  within roughly 400 ms when Barge is `stop`.
- Type during speech and confirm `stop` cuts playback while `continue` queues
  the turn until the reply finishes.
- Enable video, show an object, and ask about it; confirm `submitted` is cyan
  and includes both `[context:]` and `[+image]` when applicable.
- Say “goodbye” and confirm the agent speaks “Goodbye.” before Mode returns to
  the wake gate.

The face starts automatically with microphone and camera enabled. Their controls
mute/disable the devices without stopping the agent. Changing the audio pipeline
rebuilds only the face's audio resources while the bridge-owned agent stays up.
Barge is a live, per-session floor-policy control; it does not change whether
full-duplex capture remains active.
