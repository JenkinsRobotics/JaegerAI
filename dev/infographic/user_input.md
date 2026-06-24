# User input — how input reaches the brain

**Status: ✅ built** for keyboard + voice; 🟡 the Studio/PySide6 chat surface is contract-only (stub).

```mermaid
flowchart LR
    kbd["⌨️ TUI keyboard<br/>prompt_toolkit"] -->|"/act/chat (ChatMessage)"| bridge
    voice["🎤 voice<br/>VoiceController → AudioSessionNode"] -->|"/sense/transcript"| bridge
    studio["💻 Studio chat (stub)"] -.->|"/act/chat"| bridge
    bridge["AgentBridge<br/>inbox queue · cap 32"] --> turn["agent turn"]
    turn -->|"/sense/chat (ChatReply)"| surf["surfaces render reply"]
    turn -->|"/sense/tool (ToolEvent)"| surf
    turn -->|"/sense/request → /act/response"| perm["permission prompts"]

    classDef built fill:#15402b,stroke:#3fae6f,color:#eafff2;
    classDef partial fill:#473a14,stroke:#c9a13b,color:#fff7e0;
    class kbd,voice,bridge,turn,surf,perm built;
    class studio partial;
```

**Flow.** Three entry surfaces converge on **AgentBridge**: the TUI keyboard publishes `ChatMessage` on `/act/chat`; voice arrives as `Transcript` on `/sense/transcript`; the (stubbed) Studio chat would also use `/act/chat`. The bridge queues input, runs one turn per item, and fans results back — `ChatReply` on `/sense/chat`, tool activity on `/sense/tool`, and tier-gated permission prompts on `/sense/request` (answered via `/act/response`).

**Key files:** `interfaces/tui/app.py` + `interfaces/tui/voice_session.py` · `agent/loop/bridge.py` · `core/messages.py` · `agent/loop/bus_confirm.py`. Keyboard + voice + bridge are fully built; the PySide6 Studio chat surface is a contract-only stub.
