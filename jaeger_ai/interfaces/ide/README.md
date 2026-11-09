# Jaeger for VS Code — Controller Extension

**The IDE extension is a controller and Gateway-backed native chat participant.**

In Jaeger Desktop, `Jaeger: Open Chat` opens VS Code's native Chat workbench, where Jaeger is the default participant and native model provider. The duplicate Jaeger conversation webview is hidden there. In other IDE hosts, the same extension keeps its companion conversation panel. In every host, the Jaeger Gateway owns sessions, execution, approvals, and persistence.

---

## Architecture

```
┌─────────────────────────────────────────┐
│ Native Chat, IDE panel, or remote WebUI │  ← The conversation happens HERE
│ Jaeger Desktop / VS Code / :8790        │
└─────────────────────────────────────────┘
                   ▲
                   │ (Gateway :33418 — SSE/WebSocket)
                   ▼
┌─────────────────────────────────────────┐
│         Jaeger Agent (The Brain)        │  ← Single source of truth
│    (Memory, Tools, Skills, Personality) │
└─────────────────────────────────────────┘
                   ▲
    ┌─────────────┼─────────────┐
    │             │             │
    ▼             ▼             ▼
┌────────┐  ┌──────────┐  ┌─────────┐
│ VS Code│  │  macOS   │  │   TUI   │
│Extension│ │   App    │  │         │
│(Controller)│(Controller)│(Controller)│
└────────┘  └──────────┘  └─────────┘
```

---

## What This Extension Does

### 1. Status Bar
Shows what Jaeger is doing:
- `○ Jaeger` — Idle
- `⟳ Jaeger: Thinking...` — Processing
- `⚙ Jaeger: Running tests...` — Working
- `💬 Jaeger: Needs input` — Waiting for you

**Click the status bar to open the chat.**

### 2. Agent Status View
- Agent status orb (animated)
- Current task
- Quick action buttons (Explain, Fix, Test, Review)
- "Open Full Chat" button

Jaeger Desktop keeps this thin status view but uses the built-in Chat view for conversations. Other IDE hosts also receive the extension's conversation panel.

### 3. Code Actions (Right-Click)
Select code → Right-click → **Ask Jaeger**:
- **Explain** — Understand what the code does
- **Fix** — Fix errors and bugs
- **Write Tests** — Generate unit tests
- **Refactor** — Improve code quality
- **Add Documentation** — Generate docs/comments
- **Review** — Code review for issues

### 4. @jaeger Chat Participant
Type `@jaeger` in VS Code Chat:
- `@jaeger explain this` — Explain current selection
- `@jaeger fix` — Fix errors in current file
- `@jaeger test` — Write tests
- `@jaeger status` — Check agent status
- `@jaeger <anything>` — Send to agent (opens main chat)

### 5. Keyboard Shortcuts
| Shortcut | Action |
|----------|--------|
| `Cmd+Shift+J` | Open chat |
| `Cmd+Shift+'` | Quick ask |
| `Cmd+Shift+E` | Explain selection |

### 6. Inline Completions
Type `// TODO:` and get a ghost text suggestion to ask Jaeger to implement it.

---

## What This Extension Does NOT Do

- ❌ No competing chat backend (the host renders chat; the Gateway owns it)
- ❌ No client-owned session authority (Gateway owns durable conversation state)
- ❌ No model calls (Gateway + Ollama Cloud handle that)
- ❌ No file editing UI (agent does that via tools)

---

## Setup

### 1. Install the Extension
```bash
# From the repo
cd jaeger_ai/interfaces/ide
npm install
```

Or install the `.vsix` from releases.

### 2. Start the Gateway
```bash
jaeger gateway daemon  # Runs on 127.0.0.1:33418
```

### 3. Start the WebUI (optional remote companion)
```bash
./scripts/run-jaeger-webui.sh  # Runs on 127.0.0.1:8790
```

### 4. Set Up the Extension
- Open VS Code
- The Jaeger icon appears in the activity bar
- Click it to see agent status
- **Set your caller token**: `Cmd+Shift+P` → "Jaeger: Set Caller Token"
- **Open chat**: `Cmd+Shift+J` or click status bar

---

## Usage Examples

### Explain Code
```
1. Select a function in your editor
2. Right-click → "Ask Jaeger" → "Explain"
3. Chat opens with the explanation
```

### Fix Errors
```
1. See a red squiggle
2. Select the problematic code
3. Right-click → "Ask Jaeger" → "Fix"
4. Chat opens with the fix
```

### Quick Ask
```
1. Press Cmd+Shift+' (or Cmd+Shift+J then type)
2. Type: "How do I add authentication to this API?"
3. Chat opens with the agent's response
```

### @jaeger in Chat
```
@jaeger explain this function
@jaeger fix the type error on line 42
@jaeger write tests for this class
@jaeger status
```

---

## Configuration

| Setting | Description | Default |
|---------|-------------|---------|
| `jaeger.gatewayUrl` | Gateway endpoint | `http://127.0.0.1:33418` |
| `jaeger.webuiUrl` | Chat UI endpoint | Derived from gatewayUrl |
| `jaeger.showStatusBar` | Show status bar item | `true` |
| `jaeger.openChatInBrowser` | Open chat externally in non-Jaeger IDE hosts | `false` |
| `jaeger.autoStartGateway` | Start Gateway automatically | `false` |
| `jaeger.model` | Default model | Gateway default |

---

## Why This Architecture?

| Approach | Distributed Chat | Centralized Chat + Controllers |
|----------|---------------|-------------------------------|
| **UX** | Each feels different | One polished experience |
| **Dev Speed** | 4x the UI work | Focus on one great UI |
| **Features** | Land in some UIs first | Instantly everywhere |
| **Context** | Split across apps | One conversation thread |
| **Voice/Streaming** | Hard in VS Code | Native in web/desktop |
| **Mobile** | No mobile chat | PWA works everywhere |

**The agent is the product. The interfaces are just ways to talk to it.**

---

## Development

```bash
cd jaeger_ai/interfaces/ide
npm install
# Press F5 in VS Code to launch Extension Development Host
```

### File Structure
```
ide/
├── extension.js      # Main entry — registers commands, providers
├── controller.js     # JaegerController — the brain of the extension
├── gateway.js        # HTTP client for Jaeger Gateway
├── conversation.js   # Shared Gateway session controller for companion hosts
├── commands.js       # Slash command helpers
├── package.json      # Extension manifest
└── media/            # Icons, webview assets
```

---

## License

Same as JaegerAI — see root LICENSE.
