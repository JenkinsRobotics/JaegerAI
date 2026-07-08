# STT → LLM → TTS — the conversation loop

**Status: ✅ built** end-to-end — Kokoro TTS; local llama.cpp or external Anthropic/OpenAI.

```mermaid
flowchart TB
    t["/sense/transcript"] --> bridge["AgentBridge._on_transcript<br/>→ inbox queue"]
    bridge --> turn["agent turn — worker thread, llm_lock<br/>drive_one_turn → JaegerAgent.run_turn"]
    turn --> llm["LLM<br/>LocalLlama (GGUF) · Anthropic · OpenAI"]
    llm -->|"tool: speak"| speak["speak tool<br/>→ /act/speech (SpeechCommand)"]
    speak -->|"bus.request — waits on ack"| tts["TTSNode<br/>queue → tick → _handle"]
    tts --> kok["KokoroTTS.speak()<br/>phonemes → vocoder → PortAudio 🔊"]
    tts -->|"/sense/tts_chunk amplitude ~30 Hz"| lip(["lip-sync — see lip_sync.md"])
    tts -->|"/sense/spoken ack"| speak
    turn -->|"final text → /sense/chat"| surf["surfaces — TUI / Studio"]

    classDef built fill:#15402b,stroke:#3fae6f,color:#eafff2;
    classDef partial fill:#473a14,stroke:#c9a13b,color:#fff7e0;
    class t,bridge,turn,llm,speak,tts,kok,surf built;
    class lip partial;
```

**Flow.** `/sense/transcript` → `AgentBridge` queues it → a worker thread runs the turn (serialized by `llm_lock`) → the LLM decides and may call the **speak** tool → `speak` publishes `/act/speech` and blocks on a `/sense/spoken` ack (correlation-id matched) → `TTSNode` synthesizes via **Kokoro** (PortAudio playback) and emits `/sense/tts_chunk` amplitude for lip-sync → the final answer goes out on `/sense/chat`.

**LLM:** local `llama-cpp-python` (GGUF, default) or external (Anthropic/OpenAI) with fallback to local. **TTS:** Kokoro v0.19; voice resolved from the active character's `voice_id`.

**Key files:** `agent/loop/bridge.py` · `main.py:_run_turn_via_jaeger_agent` · `agent/loop/jaeger_agent.py` · `agent/tools/speak.py` · `nodes/kokoro_tts/node.py` · `nodes/kokoro_tts/engine.py`. Full path is real — the `/sense/tts_chunk` amplitude is a sin-wave proxy (see `lip_sync.md`).
