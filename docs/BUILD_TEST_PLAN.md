# JaegerAI Build & Test Plan — Production-Grade Frontends

**Date:** 2026-10-25
**Goal:** Build functional, testable frontends for all 10 interfaces and verify with automated tests
**Scope:** Web UI, macOS App, TUI, IDE Extension, Avatar, APIs, Mobile/PWA

---

## Executive Summary

JaegerAI has **10 frontends/interfaces** at various stages. This plan will:

1. **Audit** current state of each frontend
2. **Fix** any broken/incomplete features
3. **Build** production-ready versions
4. **Test** with automated functional tests
5. **Verify** with E2E production tests
6. **CI/CD** — automated testing on every commit

**Timeline:** 4-6 weeks for full production-grade

---

## Current State Audit

| Frontend | Status | Build System | Tests | Production Ready? |
|----------|--------|--------------|-------|-------------------|
| **Web UI (React)** | 🟡 70% | Vite | ⚠️ Partial | ❌ No |
| **WebUI Backend** | 🟢 90% | Python | ✅ Good | 🟡 Almost |
| **macOS App (Swift)** | 🟡 60% | SwiftPM/Xcode | ❌ None | ❌ No |
| **TUI (Terminal)** | 🟢 85% | Python | ⚠️ Partial | 🟡 Almost |
| **IDE Extension** | 🔴 20% | TypeScript | ❌ None | ❌ No |
| **Avatar** | 🟡 40% | SwiftPM | ❌ None | ❌ No |
| **Native Multimodal** | 🟢 80% | Python | ✅ Good | 🟡 Almost |
| **Bridge Protocol** | 🟢 90% | Python | ✅ Good | ✅ Yes |
| **A2A Server** | 🟢 85% | Python | ⚠️ Partial | 🟡 Almost |
| **MCP Server** | 🟢 85% | Python | ⚠️ Partial | 🟡 Almost |
| **Mobile/PWA** | 🟡 50% | React | ❌ None | ❌ No |

---

## Phase 1: Test Infrastructure Setup (Week 1)

### 1.1 Python Testing Stack
```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov pytest-xdist playwright pytest-playwright

# Create dev/requirements-test.txt
cat > dev/requirements-test.txt << 'EOF'
pytest>=8.0
pytest-asyncio>=0.23
pytest-cov>=4.1
pytest-xdist>=3.5
pytest-playwright>=0.4
playwright>=1.40
pytest-timeout>=2.2
pytest-mock>=3.12
httpx>=0.26
websockets>=12.0
EOF
```

### 1.2 Frontend Testing Stack (React)
```bash
cd jaeger_ai/interfaces/ui
npm install -D \
  vitest \
  @testing-library/react \
  @testing-library/jest-dom \
  @testing-library/user-event \
  @vitest/coverage-v8 \
  jsdom \
  @playwright/test
```

### 1.3 Swift Testing Stack
```bash
# Add to Package.swift or use xcodebuild test
xcodebuild test -scheme JaegerShell -destination 'platform=macOS'

# For UI tests
xcodebuild test -scheme JaegerShellUITests -destination 'platform=macOS'
```

### 1.4 Test Directory Structure
```
dev/tests/
├── unit/                    # Unit tests (fast)
│   ├── python/
│   ├── frontend/
│   └── swift/
├── integration/             # Integration tests
│   ├── gateway/
│   ├── webui/
│   └── bridge/
├── e2e/                     # End-to-end tests
│   ├── web_ui.spec.ts       # Playwright
│   ├── macos_app.spec.ts    # XCUITest
│   └── tui.spec.ts          # tmux-based
├── fixtures/                # Test data
├── helpers/                 # Test utilities
└── conftest.py              # Pytest configuration
```

### 1.5 CI/CD Pipeline (GitHub Actions)
```yaml
# .github/workflows/test.yml
name: Test Suite
on: [push, pull_request]

jobs:
  python-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r dev/requirements-test.txt
      - run: pytest dev/tests/unit/python -v --cov

  frontend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: cd jaeger_ai/interfaces/ui && npm ci
      - run: cd jaeger_ai/interfaces/ui && npm test
      - run: cd jaeger_ai/interfaces/ui && npx playwright install
      - run: cd jaeger_ai/interfaces/ui && npx playwright test

  e2e-tests:
    runs-on: ubuntu-latest
    needs: [python-tests, frontend-tests]
    steps:
      - uses: actions/checkout@v4
      - run: ./scripts/start-test-env.sh
      - run: pytest dev/tests/e2e -v
```

---

## Phase 2: Web UI (React) — Build & Test (Week 1-2)

### 2.1 Current Issues to Fix
- [ ] Install new dependencies (cmdk, react-markdown, etc.)
- [ ] Wire up `GatewayClient` to actual components
- [ ] Add `CommandPalette` to main layout
- [ ] Replace basic markdown with `MarkdownRenderer`
- [ ] Add `FileUpload` to chat input
- [ ] Wrap app in `ErrorBoundary`
- [ ] Add loading states
- [ ] Add empty states
- [ ] Fix any TypeScript errors
- [ ] Build production bundle

### 2.2 Build Commands
```bash
cd jaeger_ai/interfaces/ui

# Install dependencies
npm install

# Development
npm run dev

# Type check
npm run type-check

# Lint
npm run lint

# Build production
npm run build

# Preview production
npm run preview
```

### 2.3 Test Plan

#### Unit Tests (Vitest)
```typescript
// src/lib/gateway-client.test.ts
// src/components/CommandPalette.test.tsx
// src/components/MarkdownRenderer.test.tsx
// src/components/FileUpload.test.tsx
// src/components/ErrorBoundary.test.tsx
```

#### Integration Tests
```typescript
// Test with mock Gateway API
// Test WebSocket connection
// Test SSE fallback
// Test streaming chat
```

#### E2E Tests (Playwright)
```typescript
// tests/e2e/web-ui.spec.ts
test('user can send message and receive response', async ({ page }) => {
  await page.goto('http://localhost:8790')
  await page.fill('[data-testid="chat-input"]', 'Hello')
  await page.click('[data-testid="send-button"]')
  await expect(page.locator('[data-testid="assistant-message"]')).toBeVisible()
})

test('command palette opens with Cmd+K', async ({ page }) => {
  await page.goto('http://localhost:8790')
  await page.keyboard.press('Meta+k')
  await expect(page.locator('[data-testid="command-palette"]')).toBeVisible()
})

test('file upload works', async ({ page }) => {
  await page.goto('http://localhost:8790')
  await page.setInputFiles('[data-testid="file-input"]', 'test/fixtures/test.txt')
  await expect(page.locator('[data-testid="file-preview"]')).toBeVisible()
})
```

### 2.4 Verification Checklist
- [ ] `npm run build` succeeds
- [ ] No TypeScript errors
- [ ] All unit tests pass
- [ ] All E2E tests pass
- [ ] Production bundle size < 500KB (gzipped)
- [ ] Lighthouse score > 90

---

## Phase 3: macOS App (Swift) — Build & Test (Week 2-3)

### 3.1 Current Issues to Fix
- [ ] Verify Swift package builds
- [ ] Add XCUITest test target
- [ ] Add unit tests for Swift logic
- [ ] Test WKWebView integration
- [ ] Test Bridge connection
- [ ] Test voice features
- [ ] Add snapshot tests

### 3.2 Build Commands
```bash
cd jaeger_ai/interfaces/macos-shell

# Build debug
bash Scripts/build-shell.sh

# Or with SwiftPM
swift build -c debug

# Build release
swift build -c release

# Run tests
swift test

# Or with xcodebuild
xcodebuild test -scheme JaegerShell -destination 'platform=macOS'
```

### 3.3 Test Plan

#### Unit Tests (Swift Testing)
```swift
// Tests/JaegerShellTests/BridgeTests.swift
import Testing
@testable import JaegerShell

struct BridgeTests {
    @Test func testBridgeConnection() async throws {
        let bridge = NativeBridge()
        try await bridge.connect()
        #expect(bridge.isConnected)
    }
}
```

#### UI Tests (XCUITest)
```swift
// Tests/JaegerShellUITests/AppUITests.swift
import XCTest

final class AppUITests: XCTestCase {
    func testWindowOpens() throws {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.windows.firstMatch.exists)
    }

    func testChatInputWorks() throws {
        let app = XCUIApplication()
        app.launch()
        let input = app.textFields["chat-input"]
        input.click()
        input.typeText("Hello")
        XCTAssertEqual(input.value as? String, "Hello")
    }
}
```

#### Snapshot Tests
```swift
// Use Snapshot.swift for visual regression testing
```

### 3.4 Verification Checklist
- [ ] `swift build` succeeds (debug + release)
- [ ] App launches without crashes
- [ ] Window appears with correct size
- [ ] WKWebView loads UI
- [ ] Bridge connects to Gateway
- [ ] Voice recording works
- [ ] All unit tests pass
- [ ] All UI tests pass

---

## Phase 4: TUI (Terminal) — Build & Test (Week 3)

### 4.1 Current Issues to Fix
- [ ] Test all slash commands
- [ ] Test streaming display
- [ ] Test voice session
- [ ] Test board view
- [ ] Add integration tests

### 4.2 Test Plan

#### Unit Tests (pytest)
```python
# dev/tests/unit/python/test_tui_commands.py
import pytest
from jaeger_ai.interfaces.tui import slash_commands

def test_slash_command_registration():
    commands = slash_commands.list_commands()
    assert "help" in commands
    assert "model" in commands

def test_command_execution():
    result = slash_commands.execute("/help")
    assert "Available commands" in result
```

#### Integration Tests (tmux-based)
```python
# dev/tests/integration/test_tui.py
import pytest
import pexpect

def test_tui_starts():
    """Test TUI starts and shows welcome banner."""
    tui = pexpect.spawn('./jaeger --tui')
    tui.expect('Jaeger')
    tui.expect('>')

def test_tui_send_message():
    """Test sending a message in TUI."""
    tui = pexpect.spawn('./jaeger --tui')
    tui.expect('>')
    tui.sendline('Hello')
    tui.expect('assistant', timeout=30)

def test_tui_slash_commands():
    """Test slash commands work."""
    tui = pexpect.spawn('./jaeger --tui')
    tui.expect('>')
    tui.sendline('/help')
    tui.expect('Available commands')
```

#### E2E Tests
```python
# dev/tests/e2e/test_tui_e2e.py
def test_full_conversation():
    """Test full conversation flow in TUI."""
    tui = pexpect.spawn('./jaeger --tui')
    # Wait for ready
    tui.expect('>')
    # Send message
    tui.sendline('What is 2+2?')
    # Wait for response
    tui.expect('4', timeout=60)
    # Exit
    tui.sendline('/quit')
    tui.expect(pexpect.EOF)
```

### 4.3 Verification Checklist
- [ ] TUI starts without errors
- [ ] All slash commands work
- [ ] Streaming responses display correctly
- [ ] Voice mode works (if audio available)
- [ ] Board view renders
- [ ] All tests pass

---

## Phase 5: IDE Extension (VS Code) — Build & Test (Week 3-4)

### 5.1 Current Issues to Fix
- [ ] Complete the extension implementation
- [ ] Add sidebar webview
- [ ] Add Gateway connection
- [ ] Add commands
- [ ] Package as VSIX
- [ ] Add tests

### 5.2 Build Commands
```bash
cd jaeger_ai/interfaces/ide

# Install dependencies
npm install

# Compile
npm run compile

# Watch mode
npm run watch

# Package
npm run package  # Creates .vsix

# Install locally
code --install-extension jaeger-ai-*.vsix
```

### 5.3 Test Plan
```typescript
// src/test/suite/extension.test.ts
import * as assert from 'assert'
import * as vscode from 'vscode'

suite('Extension Test Suite', () => {
  test('Extension activates', async () => {
    const ext = vscode.extensions.getExtension('jaeger-ai')
    await ext?.activate()
    assert.ok(ext?.isActive)
  })

  test('Sidebar view exists', () => {
    const view = vscode.window.createWebviewView('jaegerChat')
    assert.ok(view)
  })
})

// E2E with VS Code Extension Testing
// Use @vscode/test-electron
```

### 5.4 Verification Checklist
- [ ] Extension compiles without errors
- [ ] VSIX package creates successfully
- [ ] Extension installs in VS Code
- [ ] Sidebar panel appears
- [ ] Chat works in sidebar
- [ ] Commands are registered
- [ ] All tests pass

---

## Phase 6: Avatar (SwiftUI) — Build & Test (Week 4)

### 6.1 Current Issues to Fix
- [ ] Complete SwiftUI implementation
- [ ] Test WebSocket connection
- [ ] Test animation rendering
- [ ] Add snapshot tests

### 6.2 Build Commands
```bash
cd jaeger_ai/interfaces/avatar

# Build
swift build

# Run
swift run

# Test
swift test

# Snapshot tests
swift test --enable-test-discovery
```

### 6.3 Test Plan
```swift
// Tests/JaegerAIAvatarTests/AvatarTests.swift
import XCTest
@testable import JaegerAIAvatar

final class AvatarTests: XCTestCase {
    func testFrameDecoder() throws {
        let decoder = FrameDecoder()
        let frame = decoder.decode(sampleData)
        XCTAssertNotNil(frame)
    }

    func testWebSocketConnection() async throws {
        let client = WebSocketClient(url: URL(string: "ws://localhost:33418/ws")!)
        try await client.connect()
        XCTAssertTrue(client.isConnected)
    }
}

// Snapshot tests with SwiftUI
// Use ViewInspector or snapshot testing library
```

---

## Phase 7: Backend APIs — Integration Tests (Week 4-5)

### 7.1 Test All Endpoints

#### REST API Tests
```python
# dev/tests/integration/test_gateway_api.py
import pytest
import httpx

@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:33418") as client:
        yield client

@pytest.mark.asyncio
async def test_health_endpoint(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_sessions_list(client):
    response = await client.get("/v1/sessions")
    assert response.status_code == 200
    assert "sessions" in response.json()

@pytest.mark.asyncio
async def test_send_turn(client):
    # Create session
    response = await client.post("/v1/sessions", json={"title": "Test"})
    session_id = response.json()["id"]
    
    # Send message
    response = await client.post(f"/v1/sessions/{session_id}/turns", json={
        "message": "Hello",
        "stream": False,
    })
    assert response.status_code == 200
```

#### WebSocket API Tests
```python
# dev/tests/integration/test_websocket_api.py
import pytest
import websockets
import json

@pytest.mark.asyncio
async def test_websocket_connection():
    async with websockets.connect("ws://127.0.0.1:33418/ws") as ws:
        # Receive welcome
        welcome = json.loads(await ws.recv())
        assert welcome["type"] == "event"
        assert welcome["event"] == "connected"
        
        # Send request
        await ws.send(json.dumps({
            "type": "req",
            "id": "test-1",
            "method": "health",
            "params": {},
        }))
        
        # Receive response
        response = json.loads(await ws.recv())
        assert response["type"] == "res"
        assert response["ok"] is True

@pytest.mark.asyncio
async def test_websocket_streaming():
    async with websockets.connect("ws://127.0.0.1:33418/ws") as ws:
        # Subscribe to events
        await ws.send(json.dumps({
            "type": "req",
            "id": "sub-1",
            "method": "events.subscribe",
            "params": {"events": ["*"]},
        }))
        
        # Send streaming request
        await ws.send(json.dumps({
            "type": "req",
            "id": "chat-1",
            "method": "chat.sendStream",
            "params": {
                "requestId": "test-stream",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        }))
        
        # Receive streaming events
        events = []
        async for message in ws:
            data = json.loads(message)
            events.append(data)
            if data.get("event") == "chat.done":
                break
            if len(events) > 100:
                break
        
        assert any(e.get("event") == "chat.delta" for e in events)
```

#### OpenAI API Tests
```python
# dev/tests/integration/test_openai_compat.py
import pytest
from openai import OpenAI

@pytest.fixture
def client():
    return OpenAI(
        base_url="http://127.0.0.1:33418/v1",
        api_key="test",
    )

def test_chat_completions(client):
    response = client.chat.completions.create(
        model="jaeger",
        messages=[{"role": "user", "content": "Hello"}],
    )
    assert response.choices[0].message.content is not None

def test_streaming(client):
    stream = client.chat.completions.create(
        model="jaeger",
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
    )
    
    chunks = []
    for chunk in stream:
        if chunk.choices[0].delta.content:
            chunks.append(chunk.choices[0].delta.content)
    
    assert len(chunks) > 0

def test_models_list(client):
    models = client.models.list()
    assert len(models.data) > 0
```

---

## Phase 8: Mobile/PWA — Build & Test (Week 5)

### 8.1 PWA Features to Add
- [ ] Service worker for offline support
- [ ] Push notifications
- [ ] Camera access
- [ ] Location tracking
- [ ] Add to home screen
- [ ] Background sync

### 8.2 Build & Test
```bash
# Build PWA
cd jaeger_ai/interfaces/ui
npm run build

# Test PWA features
npx lighthouse http://localhost:8790 --view

# Test on mobile (Playwright)
npx playwright test --project=iphone
```

### 8.3 PWA Tests
```typescript
// tests/e2e/pwa.spec.ts
test('PWA is installable', async ({ page }) => {
  await page.goto('http://localhost:8790')
  
  // Check manifest
  const manifest = await page.evaluate(() => {
    return fetch('/manifest.json').then(r => r.json())
  })
  expect(manifest.name).toBe('JaegerAI')
  
  // Check service worker
  const sw = await page.evaluate(() => navigator.serviceWorker.getRegistration())
  expect(sw).toBeTruthy()
})

test('camera access works', async ({ page, context }) => {
  await context.grantPermissions(['camera'])
  await page.goto('http://localhost:8790')
  await page.click('[data-testid="camera-button"]')
  // Verify camera preview appears
})

test('push notifications work', async ({ page, context }) => {
  await context.grantPermissions(['notifications'])
  await page.goto('http://localhost:8790')
  // Subscribe to push
  await page.click('[data-testid="enable-notifications"]')
  // Verify subscription
})
```

---

## Phase 9: E2E Production Tests (Week 5-6)

### 9.1 Full System Tests
```python
# dev/tests/e2e/test_production.py
"""
Production-grade E2E tests.
These run against a fully deployed system.
"""
import pytest
import subprocess
import time
import httpx
import websockets

@pytest.fixture(scope="session")
def running_system():
    """Start the full JaegerAI stack for E2E tests."""
    # Start Gateway
    gateway = subprocess.Popen(["jaeger", "gateway", "daemon"])
    time.sleep(5)
    
    # Start WebUI
    webui = subprocess.Popen(["./scripts/run-jaeger-webui.sh"])
    time.sleep(3)
    
    # Wait for health
    for _ in range(30):
        try:
            r = httpx.get("http://127.0.0.1:33418/health")
            if r.status_code == 200:
                break
        except:
            pass
        time.sleep(1)
    
    yield {
        "gateway": "http://127.0.0.1:33418",
        "webui": "http://127.0.0.1:8790",
        "ws": "ws://127.0.0.1:33418/ws",
    }
    
    # Cleanup
    gateway.terminate()
    webui.terminate()

@pytest.mark.e2e
def test_full_conversation_flow(running_system):
    """Test complete conversation flow from WebUI."""
    from playwright.sync_api import sync_playwright
    
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        
        # Open WebUI
        page.goto(running_system["webui"])
        
        # Create new session
        page.click('[data-testid="new-session"]')
        page.fill('[data-testid="session-title"]', 'E2E Test')
        page.click('[data-testid="create"]')
        
        # Send message
        page.fill('[data-testid="chat-input"]', 'What is the capital of France?')
        page.click('[data-testid="send"]')
        
        # Wait for response
        page.wait_for_selector('[data-testid="assistant-message"]', timeout=30000)
        response = page.text_content('[data-testid="assistant-message"]')
        assert 'Paris' in response.lower()
        
        browser.close()

@pytest.mark.e2e
def test_websocket_realtime_updates(running_system):
    """Test real-time updates via WebSocket."""
    import asyncio
    
    async def test():
        async with websockets.connect(running_system["ws"]) as ws:
            # Subscribe to events
            await ws.send(json.dumps({
                "type": "req",
                "id": "1",
                "method": "events.subscribe",
                "params": {"events": ["*"]},
            }))
            
            # Create session and send message via HTTP
            async with httpx.AsyncClient() as client:
                # Create session
                r = await client.post(
                    f"{running_system['gateway']}/v1/sessions",
                    json={"title": "WS Test"},
                )
                session_id = r.json()["id"]
                
                # Send message
                await client.post(
                    f"{running_system['gateway']}/v1/sessions/{session_id}/turns",
                    json={"message": "Hello"},
                ])
            
            # Should receive events via WebSocket
            events = []
            try:
                async for message in ws:
                    data = json.loads(message)
                    events.append(data)
                    if data.get("event") == "turn.completed":
                        break
                    if len(events) > 50:
                        break
            except asyncio.TimeoutError:
                pass
            
            assert len(events) > 0
            assert any(e.get("event") in ["turn.started", "turn.delta", "turn.completed"] for e in events)
    
    asyncio.run(asyncio.wait_for(test(), timeout=30))

@pytest.mark.e2e
def test_mobile_node_integration(running_system):
    """Test mobile node connection and capabilities."""
    from jaeger_ai.core.mobile import MobileNodeServer
    import asyncio
    
    async def test():
        # Start mobile node server
        server = MobileNodeServer()
        await server.start(port=33419)
        
        try:
            # Simulate mobile client
            async with websockets.connect("ws://127.0.0.1:33419/node") as ws:
                # Receive challenge
                challenge = json.loads(await ws.recv())
                assert challenge["event"] == "connect.challenge"
                
                # Respond (simplified)
                await ws.send(json.dumps({
                    "type": "req",
                    "id": "connect-1",
                    "method": "connect",
                    "params": {
                        "client": {
                            "id": "test-mobile",
                            "platform": "web",
                            "mode": "node",
                        },
                        "caps": ["camera", "location"],
                    },
                }))
                
                # Receive hello-ok
                response = json.loads(await ws.recv())
                assert response["ok"] is True
                
                # Test camera command
                await ws.send(json.dumps({
                    "type": "event",
                    "event": "node.invoke.request",
                    "payload": {
                        "id": "cam-1",
                        "command": "camera.snap",
                        "paramsJSON": "{}",
                    },
                }))
        finally:
            await server.stop()
    
    asyncio.run(test())
```

---

## Phase 10: CI/CD Pipeline (Week 6)

### 10.1 Complete GitHub Actions Workflow
```yaml
# .github/workflows/production.yml
name: Production Pipeline

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  # ─────────────────────────────────────────────────────────
  # 1. Lint & Type Check
  # ─────────────────────────────────────────────────────────
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      # Python
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install ruff mypy
      - run: ruff check jaeger_ai/
      - run: mypy jaeger_ai/ --ignore-missing-imports
      
      # TypeScript
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: cd jaeger_ai/interfaces/ui && npm ci
      - run: cd jaeger_ai/interfaces/ui && npm run lint
      - run: cd jaeger_ai/interfaces/ui && npm run type-check
      
      # Swift
      - uses: maxim-lobanov/setup-xcode@v1
        with:
          xcode-version: latest-stable
      - run: cd jaeger_ai/interfaces/macos-shell && swift build

  # ─────────────────────────────────────────────────────────
  # 2. Unit Tests
  # ─────────────────────────────────────────────────────────
  unit-tests:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        suite: [python, frontend, swift]
    steps:
      - uses: actions/checkout@v4
      
      - name: Python unit tests
        if: matrix.suite == 'python'
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r dev/requirements-test.txt
      - run: pytest dev/tests/unit/python -v --cov=jaeger_ai --cov-report=xml
      - uses: codecov/codecov-action@v3
      
      - name: Frontend unit tests
        if: matrix.suite == 'frontend'
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: cd jaeger_ai/interfaces/ui && npm ci
      - run: cd jaeger_ai/interfaces/ui && npm test -- --coverage
      
      - name: Swift unit tests
        if: matrix.suite == 'swift'
        uses: maxim-lobanov/setup-xcode@v1
      - run: cd jaeger_ai/interfaces/macos-shell && swift test

  # ─────────────────────────────────────────────────────────
  # 3. Integration Tests
  # ─────────────────────────────────────────────────────────
  integration-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r dev/requirements-test.txt
      - run: pip install -e .
      - run: pytest dev/tests/integration -v

  # ─────────────────────────────────────────────────────────
  # 4. E2E Tests
  # ─────────────────────────────────────────────────────────
  e2e-tests:
    runs-on: ubuntu-latest
    needs: [unit-tests, integration-tests]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      
      - run: pip install -r dev/requirements-test.txt
      - run: pip install -e .
      - run: cd jaeger_ai/interfaces/ui && npm ci && npm run build
      - run: npx playwright install chromium
      
      - name: Start test environment
        run: ./scripts/start-test-env.sh
      
      - name: Run E2E tests
        run: pytest dev/tests/e2e -v
      
      - name: Run Playwright tests
        run: cd jaeger_ai/interfaces/ui && npx playwright test
      
      - uses: actions/upload-artifact@v3
        if: failure()
        with:
          name: test-artifacts
          path: |
            test-results/
            playwright-report/
            htmlcov/

  # ─────────────────────────────────────────────────────────
  # 5. Build Artifacts
  # ─────────────────────────────────────────────────────────
  build:
    runs-on: ${{ matrix.os }}
    needs: [lint, unit-tests, integration-tests, e2e-tests]
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest]
        include:
          - os: ubuntu-latest
            artifact: linux
          - os: macos-latest
            artifact: macos
    steps:
      - uses: actions/checkout@v4
      
      # Python package
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install build
      - run: python -m build
      
      # Frontend
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: cd jaeger_ai/interfaces/ui && npm ci && npm run build
      
      # Swift (macOS only)
      - name: Build macOS app
        if: matrix.os == 'macos-latest'
        uses: maxim-lobanov/setup-xcode@v1
      - run: |
          if [ "${{ matrix.os }}" = "macos-latest" ]; then
            cd jaeger_ai/interfaces/macos-shell
            swift build -c release
          fi
      
      - uses: actions/upload-artifact@v3
        with:
          name: jaeger-ai-${{ matrix.artifact }}
          path: |
            dist/
            jaeger_ai/interfaces/ui/dist/
            jaeger_ai/interfaces/macos-shell/.build/release/
```

---

## Phase 11: Test Scripts

### 11.1 Master Test Script
```bash
#!/bin/bash
# scripts/test-all.sh — Run ALL tests

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "========================================"
echo "  JaegerAI Complete Test Suite"
echo "========================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
PASSED=0
FAILED=0
SKIPPED=0

run_test() {
    local name="$1"
    local cmd="$2"
    
    echo -n "→ $name... "
    if eval "$cmd" > /tmp/test-output.log 2>&1; then
        echo -e "${GREEN}PASS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}FAIL${NC}"
        cat /tmp/test-output.log | tail -20
        ((FAILED++))
    fi
}

# ─────────────────────────────────────────────────────────
# 1. Python Unit Tests
# ─────────────────────────────────────────────────────────
echo "## Python Tests"
run_test "Python syntax check" "python3 -m py_compile $(find jaeger_ai -name '*.py')"
run_test "Python unit tests" "pytest dev/tests/unit/python -v --tb=short"
run_test "Python coverage" "pytest dev/tests/unit/python --cov=jaeger_ai --cov-fail-under=70"

# ─────────────────────────────────────────────────────────
# 2. Frontend Tests
# ─────────────────────────────────────────────────────────
echo ""
echo "## Frontend Tests"
cd jaeger_ai/interfaces/ui
run_test "TypeScript check" "npm run type-check"
run_test "ESLint" "npm run lint"
run_test "Unit tests" "npm test -- --run"
run_test "Build" "npm run build"
cd "$REPO_ROOT"

# ─────────────────────────────────────────────────────────
# 3. Swift Tests
# ─────────────────────────────────────────────────────────
echo ""
echo "## Swift Tests"
if command -v swift &> /dev/null; then
    run_test "macOS app build" "cd jaeger_ai/interfaces/macos-shell && swift build"
    run_test "macOS app tests" "cd jaeger_ai/interfaces/macos-shell && swift test"
    run_test "Avatar build" "cd jaeger_ai/interfaces/avatar && swift build"
    run_test "Avatar tests" "cd jaeger_ai/interfaces/avatar && swift test"
else
    echo "→ Swift tests... ${YELLOW}SKIP (no Swift)${NC}"
    ((SKIPPED++))
fi

# ─────────────────────────────────────────────────────────
# 4. Integration Tests
# ─────────────────────────────────────────────────────────
echo ""
echo "## Integration Tests"
run_test "Gateway API tests" "pytest dev/tests/integration/test_gateway_api.py -v"
run_test "WebSocket tests" "pytest dev/tests/integration/test_websocket_api.py -v"
run_test "OpenAI compat tests" "pytest dev/tests/integration/test_openai_compat.py -v"
run_test "Mobile node tests" "pytest dev/tests/integration/test_mobile.py -v"

# ─────────────────────────────────────────────────────────
# 5. E2E Tests
# ─────────────────────────────────────────────────────────
echo ""
echo "## E2E Tests"
run_test "Start test environment" "./scripts/start-test-env.sh"
run_test "Web UI E2E" "cd jaeger_ai/interfaces/ui && npx playwright test"
run_test "Production E2E" "pytest dev/tests/e2e -v -m e2e"
run_test "Stop test environment" "./scripts/stop-test-env.sh"

# ─────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  Test Summary"
echo "========================================"
echo -e "  Passed:  ${GREEN}$PASSED${NC}"
echo -e "  Failed:  ${RED}$FAILED${NC}"
echo -e "  Skipped: ${YELLOW}$SKIPPED${NC}"
echo ""

if [ $FAILED -gt 0 ]; then
    echo -e "${RED}❌ Some tests failed!${NC}"
    exit 1
else
    echo -e "${GREEN}✅ All tests passed!${NC}"
    exit 0
fi
```

### 11.2 Quick Test Scripts
```bash
# scripts/test-web-ui.sh — Test Web UI only
# scripts/test-macos-app.sh — Test macOS app only
# scripts/test-tui.sh — Test TUI only
# scripts/test-api.sh — Test all APIs only
# scripts/test-e2e.sh — Test E2E only
```

---

## Phase 12: Documentation

### 12.1 Test Documentation
- `docs/testing/README.md` — Overview
- `docs/testing/unit-tests.md` — How to write unit tests
- `docs/testing/integration-tests.md` — How to write integration tests
- `docs/testing/e2e-tests.md` — How to write E2E tests
- `docs/testing/ci-cd.md` — CI/CD pipeline

### 12.2 Run Documentation
- `docs/testing/running-tests.md` — How to run tests locally
- `docs/testing/debugging-tests.md` — How to debug failing tests
- `docs/testing/coverage.md` — Coverage reports

---

## Timeline Summary

| Week | Phase | Deliverables |
|------|-------|--------------|
| **1** | Test Infrastructure + Web UI | Test framework, CI/CD, Web UI tests |
| **2** | Web UI Complete + macOS App Start | Production Web UI, macOS build |
| **3** | macOS App + TUI | macOS app tests, TUI tests |
| **4** | IDE Extension + Avatar | VS Code extension, Avatar app |
| **5** | Backend APIs + Mobile/PWA | API tests, PWA tests |
| **6** | E2E + CI/CD + Docs | Full E2E suite, CI pipeline, docs |

---

## Success Criteria

### Production-Ready Checklist
- [ ] All frontends build without errors
- [ ] All tests pass (unit + integration + E2E)
- [ ] Code coverage > 70%
- [ ] CI/CD pipeline runs on every commit
- [ ] No critical bugs
- [ ] Performance benchmarks met
- [ ] Documentation complete
- [ ] Release artifacts generated

### Performance Targets
- Web UI: First load < 2s, bundle < 500KB gzipped
- macOS App: Launch < 1s, memory < 100MB idle
- TUI: Response < 100ms
- API: p99 latency < 100ms
- WebSocket: < 50ms message latency

---

## Next Steps

1. **Review this plan** — adjust timeline/scope as needed
2. **Start Phase 1** — set up test infrastructure
3. **Start Phase 2** — fix and test Web UI
4. **Continue through phases**
5. **Final verification** — run full test suite

---

*Plan created: 2026-10-25*
*Estimated completion: 4-6 weeks*
*Total test files to create: ~50*
*Total test cases: ~200+*
