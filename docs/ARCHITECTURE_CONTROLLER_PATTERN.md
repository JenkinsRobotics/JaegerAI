# Architecture: Centralized Brain + Thin Controllers

**Date:** 2026-10-26
**Status:** Adopted
**Version:** v0.13.0

---

## The Big Idea

> **The agent is the product. The interfaces are just ways to talk to it.**

Instead of building 4 different chat UIs (VS Code, macOS, Web, TUI), we build:

1. **ONE amazing chat UI** (Apple-Native Web)
2. **Many thin controllers** that feed context and intent into the chat

---

## The Pattern

```
┌─────────────────────────────────────────┐
│     ONE Chat UI (Apple-Native Web)      │  ← The conversation happens HERE
│     127.0.0.1:8790/?ui=apple            │
│                                         │
│  • ChatGPT-style messages               │
│  • Voice orb + waveform                 │
│  • Streaming responses                  │
│  • File uploads                         │
│  • Session history                      │
│  • Memory browser                       │
└─────────────────────────────────────────┘
                   ▲
                   │ (Gateway :33418 — SSE/WebSocket)
                   ▼
┌─────────────────────────────────────────┐
│         Jaeger Agent (The Brain)        │  ← Single source of truth
│                                         │
│  • Memory (5-tier taxonomy)             │
│  • Tools (file, shell, web, NAS, etc.)  │
│  • Skills (Hermes, OpenClaw, custom)    │
│  • Personality                          │
│  • Verification (EffectLedger)          │
│                                         │
│  Connected to: Ollama Cloud / Local     │
└─────────────────────────────────────────┘
                   ▲
    ┌─────────────┼─────────────┬─────────────┐
    │             │             │             │
    ▼             ▼             ▼             ▼
┌────────┐  ┌──────────┐  ┌─────────┐  ┌─────────┐
│ VS Code│  │  macOS   │  │   TUI   │  │ Discord │
│Extension│ │   App    │  │         │  │   Bot   │
│        │  │          │  │         │  │         │
│CONTROLLER│CONTROLLER │CONTROLLER│CONTROLLER│
└────────┘  └──────────┘  └─────────┘  └─────────┘
```

---

## What Each Controller Does

### VS Code Extension (Controller)
**Not a chat UI — a remote control for the agent.**

| Feature | Description |
|---------|-------------|
| **Status Bar** | Shows what Jaeger is doing (idle/thinking/working) |
| **Sidebar** | Agent state, quick actions, recent tasks |
| **Code Actions** | Right-click → "Ask Jaeger" (explain, fix, test, refactor) |
| **@jaeger** | Chat participant that routes to the agent |
| **Keyboard** | `Cmd+Shift+J` opens chat, `Cmd+Shift+'` quick ask |
| **Inline** | `// TODO:` triggers ghost text suggestion |
| **Click** | Status bar click → opens main chat |

**What it sends to the Gateway:**
```javascript
{
  text: "Explain this code in server.py (lines 42-56)",
  source: "vscode",
  context: {
    code: "def process(data):\n    ...",
    file: "server.py",
    language: "python",
    startLine: 42,
    endLine: 56,
    diagnostics: "Line 44: unused variable 'x'",
    workspace: "/Users/me/project",
    ide: "vscode"
  }
}
```

**What it does NOT do:**
- ❌ No chat UI
- ❌ No conversation state
- ❌ No model calls

---

### macOS App (Controller)
**Menu bar orb + quick input pill.**

| Feature | Description |
|---------|-------------|
| **Menu Bar** | Animated orb showing agent state |
| **Hotkey** | `⌥Space` opens quick input pill |
| **Voice** | Click orb to record voice message |
| **Status** | Shows current task in menu |
| **Click** | Opens main chat in WKWebView |

---

### TUI (Controller)
**Terminal interface for power users.**

| Feature | Description |
|---------|-------------|
| `jaeger ask "..."` | Quick command |
| `jaeger status` | Check agent state |
| `jaeger chat` | Full TUI chat (for SSH/no-GUI) |
| `jaeger tasks` | List active tasks |

---

### Discord/Slack Bot (Future Controller)
**Just another way to talk to the agent.**

```
User in Discord: "Hey Jaeger, deploy to NAS"
        ↓
Discord Bot sends to Gateway:
{
  text: "deploy to NAS",
  source: "discord",
  context: { channel: "#engineering", user: "matt" }
}
        ↓
Response streams back to Discord AND appears in main chat
```

---

## Why This Is Better

| Approach | Distributed Chat (4 UIs) | Centralized Chat + Controllers |
|----------|-------------------------|-------------------------------|
| **UX Consistency** | 😞 Each feels different | ✅ One polished experience |
| **Development Speed** | 😞 4x the UI work | ✅ Focus on one great UI |
| **Feature Parity** | 😞 Features land in some UIs first | ✅ New feature = instantly everywhere |
| **Context Switching** | 😞 Chat history split across apps | ✅ One conversation thread |
| **Voice/Streaming** | 😞 Hard to do well in VS Code | ✅ Native in web/desktop |
| **Mobile Access** | 😞 No mobile chat | ✅ PWA works everywhere |
| **Agent State** | 😞 Each client tracks separately | ✅ Gateway is single source of truth |
| **Adding New Client** | 😞 Build full chat UI | ✅ Just send intent to Gateway |

---

## The Protocol

### Controller → Gateway

```javascript
// Send intent
POST /v1/sessions/:id/turns
{
  "text": "Explain this code",
  "source": "vscode",           // Who sent this
  "context": {
    "code": "...",              // Optional: selected code
    "file": "server.py",        // Optional: file path
    "language": "python",       // Optional: language
    "workspace": "/project",    // Optional: workspace
    "ide": "vscode"             // Optional: IDE info
  }
}
```

### Gateway → All Clients (SSE/WebSocket)

```javascript
// Broadcast to all connected clients
{
  "event": "turn.delta",
  "session_id": "abc-123",
  "payload": {
    "delta": "This function...",
    "source": "assistant"
  }
}
```

**Every client sees the same conversation in real-time.**

---

## Implementation Status

| Controller | Status | Chat UI | Notes |
|------------|--------|---------|-------|
| **Apple-Native Web** | ✅ Done | — | The ONE chat |
| **VS Code Extension** | ✅ Done | Links to web | Controller pattern |
| **macOS App** | 🟡 Existing | WKWebView | Needs controller polish |
| **TUI** | 🟡 Existing | prompt_toolkit | Already thin client |
| **Discord Bot** | ⬜ Future | Links to web | Easy to add |
| **Slack Bot** | ⬜ Future | Links to web | Easy to add |
| **Mobile PWA** | 🟡 CSS ready | — | Same as web |

---

## Building a New Controller

Want to add a new way to talk to Jaeger? Follow this pattern:

### 1. Create the Controller
```javascript
// my-controller.js
const { Gateway } = require('./gateway');

class MyController {
  constructor() {
    this.gateway = new Gateway('http://127.0.0.1:33418');
  }

  async send(message, context = {}) {
    // 1. Gather context
    const fullContext = {
      ...context,
      source: 'my-controller',
      timestamp: Date.now(),
    };

    // 2. Send to Gateway (creates/reuses session)
    const session = await this.getOrCreateSession();
    await this.gateway.send(session.id, {
      text: message,
      source: 'my-controller',
      context: fullContext,
    });

    // 3. Open main chat (or show notification)
    this.openChat();
  }

  openChat() {
    // Open http://127.0.0.1:8790/?ui=apple
  }
}
```

### 2. Show Status (Optional)
```javascript
// Poll Gateway for agent state
async pollStatus() {
  const health = await this.gateway.json('/health');
  const state = health.diagnostics?.owner_runtime;
  // Update your UI: "Jaeger is thinking..."
}
```

### 3. Subscribe to Events (Optional)
```javascript
// Real-time updates
const stream = await this.gateway.events(sessionId);
for await (const event of stream) {
  // Update your UI with turn.delta, tool.call, etc.
}
```

---

## Key Files

| File | Purpose |
|------|---------|
| `jaeger_ai/interfaces/ui/src/AppleApp.tsx` | The ONE chat UI |
| `jaeger_ai/interfaces/ui/src/theme/apple-app.css` | Chat UI styles |
| `jaeger_ai/interfaces/ui/src/components/VoiceOrb.tsx` | Voice orb |
| `jaeger_ai/interfaces/ide/extension.js` | VS Code controller entry |
| `jaeger_ai/interfaces/ide/controller.js` | VS Code controller logic |
| `jaeger_ai/interfaces/ide/gateway.js` | Gateway HTTP client |
| `jaeger_ai/core/gateway/server.py` | The brain (Gateway) |
| `jaeger_ai/core/gateway/websocket.py` | WebSocket support |

---

## Migration from Old Pattern

### Before (Distributed Chat)
```
VS Code Extension:  [Chat UI] ←→ Gateway
macOS App:          [Chat UI] ←→ Gateway
Web UI:             [Chat UI] ←→ Gateway
TUI:                [Chat UI] ←→ Gateway
```

### After (Centralized + Controllers)
```
Apple-Native Web:   [Chat UI] ←→ Gateway ←→ [Agent]
                                        ▲
VS Code Extension:  [Controller] ────────┘
macOS App:          [Controller] ────────┘
TUI:                [Controller] ────────┘
```

---

## Summary

| Question | Answer |
|----------|--------|
| Where is the chat? | Apple-Native Web UI (`?ui=apple`) |
| What does VS Code do? | Sends context, shows status, opens chat |
| What does macOS do? | Menu bar orb, quick input, opens chat |
| Can I chat from Discord? | Yes — bot sends intent, response in main chat |
| Is conversation state synced? | Yes — Gateway owns it, all clients see it |
| Can I use voice in VS Code? | No — click status bar to open chat |
| Mobile? | Same web UI works on iPhone/Android |

**One agent. One chat. Many ways to talk to it.**

---

*Architecture Document — 2026-10-26*
*JaegerAI v0.13.0 — Controller Pattern*
