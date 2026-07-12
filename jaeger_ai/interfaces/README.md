# interfaces/ — drivers (TUI / voice / REPL)

> **Modification tier: C — Framework core.** UI plumbing. Edits here
> affect how the user talks to the agent. Test the affected interface
> interactively after any change. Full policy:
> [`/docs/SELF_MODIFICATION_BOUNDARIES.md`](../../../docs/SELF_MODIFICATION_BOUNDARIES.md).

## What's in here

| Dir | Driver |
|---|---|
| [`tui/`](tui/) | The interactive TUI (the `jaeger-os` command). prompt_toolkit-based pinned status bar, slash commands, live activity indicator. |
| [`voice/`](voice/) | Always-listening voice loop — STT (whisper.cpp) + TTS (Kokoro / ElevenLabs / Edge) + the wake-word + barge-in cancel path. |

## Common contracts

Each driver calls into `main.py:run_command` / `main.py:run_for_voice`
— they're the canonical turn entry. Drivers shouldn't reach inside the
agent loop directly; if you need a hook the loop doesn't expose,
extend `AgentCallbacks` in `agent/callbacks.py` rather than reaching
around it.
