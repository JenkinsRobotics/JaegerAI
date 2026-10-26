/**
 * Jaeger Controller Client — The IDE extension as a CONTROLLER, not a chat UI.
 *
 * Philosophy: The Apple-Native Web UI is the ONE chat. The VS Code extension
 * is a thin controller that:
 * - Sends context (selected code, file, diagnostics) TO the agent
 * - Shows agent state (what's Jaeger working on?)
 * - Provides quick actions (fix, explain, test, refactor)
 * - Opens the main chat when you need to see/talk
 *
 * Architecture:
 *   VS Code Extension (Controller)
 *          │
 *          │ HTTP/WebSocket to Gateway :33418
 *          ▼
 *   Jaeger Gateway (The Brain)
 *          │
 *          ▼
 *   Ollama Cloud / Local Model
 *          │
 *          ▼
 *   Apple-Native Chat UI (The Conversation)
 *
 * The extension NEVER maintains its own conversation state.
 * It's a remote control for the agent.
 */

'use strict';

const vscode = require('vscode');
const { Gateway, GatewayError } = require('./gateway');
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────

/**
 * @typedef {Object} AgentState
 * @property {'idle'|'thinking'|'working'|'waiting'|'error'} status
 * @property {string} [currentTask]
 * @property {string} [sessionId]
 * @property {number} [timestamp]
 */

/**
 * @typedef {Object} CodeContext
 * @property {string} code - Selected or current file content
 * @property {string} file - Relative file path
 * @property {string} language - Programming language
 * @property {number} [startLine] - Selection start (1-based)
 * @property {number} [endLine] - Selection end (1-based)
 * @property {string} [diagnostics] - Any errors/warnings on this code
 */

// ─────────────────────────────────────────────────────────────
// Controller Client
// ─────────────────────────────────────────────────────────────

class JaegerController {
  /**
   * @param {vscode.ExtensionContext} context
   * @param {Gateway} gateway
   */
  constructor(context, gateway) {
    this.context = context;
    this.gateway = gateway;
    this._state = { status: 'idle' };
    this._statusBarItem = null;
    this._listeners = new Set();
    this._pollInterval = null;
    this._sessionId = null;
  }

  // ─────────────────────────────────────────────────────────
  // Lifecycle
  // ─────────────────────────────────────────────────────────

  activate() {
    this._createStatusBar();
    this._startPolling();
    this._connectEvents();
    return this;
  }

  dispose() {
    if (this._pollInterval) clearInterval(this._pollInterval);
    if (this._statusBarItem) this._statusBarItem.dispose();
    this._listeners.clear();
  }

  // ─────────────────────────────────────────────────────────
  // State Management
  // ─────────────────────────────────────────────────────────

  /**
   * Current agent state
   * @returns {AgentState}
   */
  get state() {
    return { ...this._state };
  }

  /**
   * Subscribe to state changes
   * @param {(state: AgentState) => void} listener
   * @returns {vscode.Disposable}
   */
  onStateChange(listener) {
    this._listeners.add(listener);
    return new vscode.Disposable(() => this._listeners.delete(listener));
  }

  _setState(partial) {
    const prev = this._state;
    this._state = { ...this._state, ...partial, timestamp: Date.now() };
    this._updateStatusBar();
    this._listeners.forEach(l => {
      try { l(this._state); } catch (e) { console.error('[JaegerController]', e); }
    });
  }

  // ─────────────────────────────────────────────────────────
  // Status Bar
  // ─────────────────────────────────────────────────────────

  _createStatusBar() {
    this._statusBarItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      100
    );
    this._statusBarItem.command = 'jaeger.openChat';
    this._updateStatusBar();
    this._statusBarItem.show();
    this.context.subscriptions.push(this._statusBarItem);
  }

  _updateStatusBar() {
    if (!this._statusBarItem) return;
    const { status, currentTask } = this._state;
    const icons = {
      idle: '$(circle-outline)',
      thinking: '$(loading~spin)',
      working: '$(gear~spin)',
      waiting: '$(comment-discussion)',
      error: '$(error)',
    };
    const labels = {
      idle: 'Jaeger',
      thinking: 'Jaeger: Thinking...',
      working: `Jaeger: ${this._truncate(currentTask || 'Working...', 30)}`,
      waiting: 'Jaeger: Needs input',
      error: 'Jaeger: Error',
    };
    this._statusBarItem.text = `${icons[status] || icons.idle} ${labels[status] || labels.idle}`;
    this._statusBarItem.tooltip = this._getTooltip();
    // Color coding
    this._statusBarItem.backgroundColor =
      status === 'error' ? new vscode.ThemeColor('statusBarItem.errorBackground') :
      status === 'waiting' ? new vscode.ThemeColor('statusBarItem.warningBackground') :
      undefined;
  }

  _getTooltip() {
    const { status, currentTask, sessionId } = this._state;
    const lines = [`Jaeger Agent — ${status}`];
    if (currentTask) lines.push(`Task: ${currentTask}`);
    if (sessionId) lines.push(`Session: ${sessionId.slice(0, 8)}...`);
    lines.push('', 'Click to open chat');
    return lines.join('\n');
  }

  _truncate(text, max) {
    return text.length > max ? text.slice(0, max - 1) + '…' : text;
  }

  // ─────────────────────────────────────────────────────────
  // Polling & Events
  // ─────────────────────────────────────────────────────────

  _startPolling() {
    // Poll agent state every 5 seconds
    this._pollInterval = setInterval(async () => {
      try {
        await this._pollState();
      } catch (e) {
        // Silent fail — Gateway might be down
      }
    }, 5000);
  }

  async _pollState() {
    try {
      const health = await this.gateway.json('/health');
      const diagnostics = health?.diagnostics || {};
      const ownerRuntime = diagnostics?.owner_runtime || {};

      // Determine state from health data
      let status = 'idle';
      let currentTask = null;

      if (ownerRuntime.execution_verified === false && ownerRuntime.resident) {
        status = 'thinking';
      }

      this._setState({ status, currentTask });
    } catch (e) {
      this._setState({ status: 'error' });
    }
  }

  _connectEvents() {
    // Listen for workspace changes that might affect agent context
    vscode.workspace.onDidChangeTextDocument(e => {
      // Could notify agent of file changes if needed
    });
    vscode.window.onDidChangeActiveTextEditor(editor => {
      this._activeEditor = editor;
    });
  }

  // ─────────────────────────────────────────────────────────
  // Context Gathering
  // ─────────────────────────────────────────────────────────

  /**
   * Get current code context (selection or current file)
   * @returns {CodeContext | null}
   */
  getCodeContext() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return null;

    const document = editor.document;
    const selection = editor.selection;
    const workspaceFolder = vscode.workspace.getWorkspaceFolder(document.uri);

    // Get selection or current line
    let code = '';
    let startLine = 0;
    let endLine = 0;

    if (!selection.isEmpty) {
      code = document.getText(selection);
      startLine = selection.start.line + 1;
      endLine = selection.end.line + 1;
    } else {
      // Get current line
      const line = document.lineAt(selection.active.line);
      code = line.text;
      startLine = selection.active.line + 1;
      endLine = startLine;
    }

    // Get diagnostics for this file
    const diagnostics = vscode.languages.getDiagnostics(document.uri);
    const diagText = diagnostics.length > 0
      ? diagnostics.slice(0, 5).map(d =>
          `Line ${d.range.start.line + 1}: ${d.message}`
        ).join('\n')
      : '';

    // Relative path
    const file = workspaceFolder
      ? path.relative(workspaceFolder.uri.fsPath, document.uri.fsPath)
      : document.uri.fsPath;

    return {
      code,
      file,
      language: document.languageId,
      startLine,
      endLine,
      diagnostics: diagText,
    };
  }

  /**
   * Get workspace context
   * @returns {Object}
   */
  getWorkspaceContext() {
    const folders = vscode.workspace.workspaceFolders || [];
    return {
      folders: folders.map(f => f.uri.fsPath),
      name: folders[0]?.name || 'No workspace',
    };
  }

  // ─────────────────────────────────────────────────────────
  // Actions — Send Intent to Gateway
  // ─────────────────────────────────────────────────────────

  /**
   * Send a message to the agent (opens chat if needed)
   * @param {string} message
   * @param {Object} [context] - Additional context
   * @returns {Promise<Object>}
   */
  async ask(message, context = {}) {
    const codeContext = context.includeCode ? this.getCodeContext() : null;
    const workspace = this.getWorkspaceContext();

    const payload = {
      text: message,
      source: 'vscode',
      context: {
        ...context,
        code: codeContext,
        workspace,
        ide: 'vscode',
      },
    };

    this._setState({ status: 'thinking' });

    try {
      // Create or use existing session
      if (!this._sessionId) {
        const session = await this.gateway.create({
          title: `VS Code: ${message.slice(0, 50)}`,
          source: 'vscode',
        });
        this._sessionId = session.id || session.session_id;
      }

      // Send the turn
      const result = await this.gateway.send(this._sessionId, payload);

      this._setState({
        status: 'thinking',
        currentTask: message.slice(0, 50),
        sessionId: this._sessionId,
      });

      // Open the chat UI to show the response
      await this.openChat();

      return result;
    } catch (error) {
      this._setState({ status: 'error' });
      throw error;
    }
  }

  /**
   * Explain selected code
   */
  async explainCode() {
    const ctx = this.getCodeContext();
    if (!ctx) {
      vscode.window.showWarningMessage('No code selected to explain.');
      return;
    }

    const hasSelection = ctx.startLine !== ctx.endLine || ctx.code.length > 80;
    const what = hasSelection ? 'this code' : 'this line';

    await this.ask(
      `Explain ${what} in ${ctx.file}${ctx.startLine ? ` (lines ${ctx.startLine}-${ctx.endLine})` : ''}:\n\n\`\`\`${ctx.language}\n${ctx.code}\n\`\`\``,
      { includeCode: true }
    );
  }

  /**
   * Fix errors in selected code or current file
   */
  async fixCode() {
    const ctx = this.getCodeContext();
    if (!ctx) {
      vscode.window.showWarningMessage('No code to fix.');
      return;
    }

    let prompt = `Fix the following code in ${ctx.file}`;
    if (ctx.diagnostics) {
      prompt += `:\n\nDiagnostics:\n${ctx.diagnostics}\n\n`;
    }
    if (ctx.startLine !== ctx.endLine) {
      prompt += `Code (lines ${ctx.startLine}-${ctx.endLine}):`;
    } else {
      prompt += `Code (line ${ctx.startLine}):`;
    }
    prompt += `\n\`\`\`${ctx.language}\n${ctx.code}\n\`\`\``;

    await this.ask(prompt, { includeCode: true });
  }

  /**
   * Write tests for selected code
   */
  async writeTests() {
    const ctx = this.getCodeContext();
    if (!ctx) {
      vscode.window.showWarningMessage('No code selected to test.');
      return;
    }

    await this.ask(
      `Write comprehensive unit tests for this ${ctx.language} code in ${ctx.file}:\n\n\`\`\`${ctx.language}\n${ctx.code}\n\`\`\`\n\nInclude edge cases, error handling, and follow best practices for ${ctx.language} testing.`,
      { includeCode: true }
    );
  }

  /**
   * Refactor selected code
   */
  async refactorCode() {
    const ctx = this.getCodeContext();
    if (!ctx) {
      vscode.window.showWarningMessage('No code selected to refactor.');
      return;
    }

    await this.ask(
      `Refactor this ${ctx.language} code in ${ctx.file} to improve readability, performance, and maintainability:\n\n\`\`\`${ctx.language}\n${ctx.code}\n\`\`\`\n\nExplain what you changed and why.`,
      { includeCode: true }
    );
  }

  /**
   * Add documentation/comments
   */
  async documentCode() {
    const ctx = this.getCodeContext();
    if (!ctx) {
      vscode.window.showWarningMessage('No code selected to document.');
      return;
    }

    await this.ask(
      `Add comprehensive documentation and comments to this ${ctx.language} code in ${ctx.file}:\n\n\`\`\`${ctx.language}\n${ctx.code}\n\`\`\`\n\nFollow ${ctx.language} documentation conventions (JSDoc, docstrings, etc.).`,
      { includeCode: true }
    );
  }

  /**
   * Review code for issues
   */
  async reviewCode() {
    const ctx = this.getCodeContext();
    if (!ctx) {
      vscode.window.showWarningMessage('No code selected to review.');
      return;
    }

    await this.ask(
      `Review this ${ctx.language} code in ${ctx.file} for bugs, security issues, performance problems, and best practice violations:\n\n\`\`\`${ctx.language}\n${ctx.code}\n\`\`\`\n\nProvide specific, actionable feedback.`,
      { includeCode: true }
    );
  }

  /**
   * Run project tests (delegates to Gateway)
   */
  async runTests() {
    await this.ask(
      `Run the test suite for this project. Workspace: ${this.getWorkspaceContext().name}\n\nReport the results and fix any failures.`,
      { runTests: true }
    );
  }

  /**
   * Check agent status
   */
  async checkStatus() {
    try {
      const health = await this.gateway.json('/health');
      const lines = [
        `Gateway: ${health.service} v${health.version}`,
        `Model: ${health.model || 'default'}`,
        `Status: ${health.status}`,
        `All checks green: ${health.all_green ? 'Yes' : 'No'}`,
      ];
      vscode.window.showInformationMessage(lines.join('\n'), { modal: true });
    } catch (error) {
      vscode.window.showErrorMessage(`Gateway connection failed: ${error.message}`);
    }
  }

  // ─────────────────────────────────────────────────────────
  // Open Main Chat
  // ─────────────────────────────────────────────────────────

  /**
   * Open the Apple-Native chat UI
   * Tries: 1) VS Code Simple Browser, 2) External browser
   */
  async openChat() {
    const config = vscode.workspace.getConfiguration('jaeger');
    const gatewayUrl = config.get('gatewayUrl') || 'http://127.0.0.1:33418';
    const webuiUrl = gatewayUrl.replace(':33418', ':8790'); // WebUI proxy port
    const appleUrl = `${webuiUrl}/?ui=apple`;

    // Try to open in VS Code's Simple Browser first
    try {
      await vscode.commands.executeCommand('vscode.openWith', vscode.Uri.parse(appleUrl), 'vscode.simpleBrowser', {
        viewColumn: vscode.ViewColumn.Beside,
      });
    } catch (e) {
      // Fallback to external browser
      vscode.env.openExternal(vscode.Uri.parse(appleUrl));
    }
  }

  /**
   * Open chat for a specific session
   * @param {string} sessionId
   */
  async openChatSession(sessionId) {
    const config = vscode.workspace.getConfiguration('jaeger');
    const gatewayUrl = config.get('gatewayUrl') || 'http://127.0.0.1:33418';
    const webuiUrl = gatewayUrl.replace(':33418', ':8790');
    const url = `${webuiUrl}/?ui=apple&session=${sessionId}`;

    try {
      await vscode.commands.executeCommand('vscode.openWith', vscode.Uri.parse(url), 'vscode.simpleBrowser', {
        viewColumn: vscode.ViewColumn.Beside,
      });
    } catch (e) {
      vscode.env.openExternal(vscode.Uri.parse(url));
    }
  }
}

// ─────────────────────────────────────────────────────────────
// Code Action Provider — Right-click menu items
// ─────────────────────────────────────────────────────────────

class JaegerCodeActionProvider {
  constructor(controller) {
    this.controller = controller;
  }

  provideCodeActions(document, range, context, token) {
    const actions = [];

    // Only show for code files
    if (document.uri.scheme !== 'file') return actions;

    // Explain
    const explainAction = new vscode.CodeAction('Ask Jaeger: Explain this', vscode.CodeActionKind.QuickFix);
    explainAction.command = {
      command: 'jaeger.explainCode',
      title: 'Explain this code',
    };
    explainAction.isPreferred = false;
    actions.push(explainAction);

    // Fix
    const fixAction = new vscode.CodeAction('Ask Jaeger: Fix this', vscode.CodeActionKind.QuickFix);
    fixAction.command = {
      command: 'jaeger.fixCode',
      title: 'Fix this code',
    };
    actions.push(fixAction);

    // Test
    const testAction = new vscode.CodeAction('Ask Jaeger: Write tests', vscode.CodeActionKind.Refactor);
    testAction.command = {
      command: 'jaeger.writeTests',
      title: 'Write tests for this',
    };
    actions.push(testAction);

    // Refactor
    const refactorAction = new vscode.CodeAction('Ask Jaeger: Refactor', vscode.CodeActionKind.RefactorRewrite);
    refactorAction.command = {
      command: 'jaeger.refactorCode',
      title: 'Refactor this code',
    };
    actions.push(refactorAction);

    // Document
    const docAction = new vscode.CodeAction('Ask Jaeger: Add documentation', vscode.CodeActionKind.Refactor);
    docAction.command = {
      command: 'jaeger.documentCode',
      title: 'Document this code',
    };
    actions.push(docAction);

    // Review
    const reviewAction = new vscode.CodeAction('Ask Jaeger: Review code', vscode.CodeActionKind.RefactorExtract);
    reviewAction.command = {
      command: 'jaeger.reviewCode',
      title: 'Review this code',
    };
    actions.push(reviewAction);

    return actions;
  }
}

// ─────────────────────────────────────────────────────────────
// Inline Completions Provider — Ghost text suggestions
// ─────────────────────────────────────────────────────────────

class JaegerInlineCompletionsProvider {
  constructor(controller) {
    this.controller = controller;
  }

  async provideInlineCompletionItems(document, position, context, token) {
    // Only trigger on specific patterns (e.g., "// TODO:", "// FIXME:")
    const line = document.lineAt(position);
    const textBefore = line.text.slice(0, position.character);

    const triggers = ['// TODO:', '// FIXME:', '// HACK:', '// NOTE: jaeger'];
    const matched = triggers.find(t => textBefore.trim().endsWith(t));

    if (!matched) return null;

    // Create a completion that asks Jaeger to fill in the TODO
    const completion = new vscode.InlineCompletionItem(
      new vscode.SnippetString(' ← Ask Jaeger to implement this'),
      new vscode.Range(position, position)
    );

    // Store context for the command
    completion.command = {
      command: 'jaeger.implementTodo',
      title: 'Implement this TODO',
      arguments: [document, position, textBefore],
    };

    return [completion];
  }
}

// ─────────────────────────────────────────────────────────────
// Status Bar Provider — Agent state in the status bar
// ─────────────────────────────────────────────────────────────

// Already implemented in JaegerController._createStatusBar()

// ─────────────────────────────────────────────────────────────
// Sidebar View Provider — Agent state, not chat
// ─────────────────────────────────────────────────────────────

class JaegerSidebarProvider {
  constructor(controller) {
    this.controller = controller;
    this._view = null;
  }

  resolveWebviewView(webviewView) {
    this._view = webviewView;
    webviewView.webview.options = { enableScripts: true };
    webviewView.webview.html = this._getHtml(webviewView.webview);

    // Handle messages from webview
    webviewView.webview.onDidReceiveMessage(message => {
      switch (message.command) {
        case 'openChat':
          this.controller.openChat();
          break;
        case 'ask':
          this.controller.ask(message.text, message.context);
          break;
        case 'checkStatus':
          this.controller.checkStatus();
          break;
      }
    });

    // Update webview when state changes
    this.controller.onStateChange(state => {
      webviewView.webview.postMessage({ type: 'state', state });
    });

    // Send initial state
    webviewView.webview.postMessage({ type: 'state', state: this.controller.state });
  }

  _getHtml(webview) {
    const nonce = getNonce();
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
  <title>Jaeger</title>
  <style>
    body {
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      color: var(--vscode-foreground);
      padding: 12px;
      margin: 0;
    }
    .header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 16px;
    }
    .orb {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background: linear-gradient(135deg, #007AFF, #5856D6, #AF52DE);
      animation: pulse 2s ease-in-out infinite;
    }
    .orb.thinking { animation: spin 1s linear infinite; }
    .orb.working { animation: bounce 1s ease-in-out infinite; }
    .orb.error { background: #FF3B30; animation: none; }
    @keyframes pulse { 0%, 100% { transform: scale(1); opacity: 0.8; } 50% { transform: scale(1.1); opacity: 1; } }
    @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
    @keyframes bounce { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
    .title { font-weight: 600; font-size: 14px; }
    .status { color: var(--vscode-descriptionForeground); font-size: 12px; margin-top: 2px; }
    .section { margin-bottom: 16px; }
    .section-title {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--vscode-descriptionForeground);
      margin-bottom: 8px;
    }
    .button {
      display: flex;
      align-items: center;
      gap: 8px;
      width: 100%;
      padding: 8px 12px;
      margin-bottom: 4px;
      background: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
      text-align: left;
    }
    .button:hover { background: var(--vscode-button-secondaryHoverBackground); }
    .button.primary {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
    }
    .button.primary:hover { background: var(--vscode-button-hoverBackground); }
    .quick-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
    .quick-actions .button { font-size: 11px; padding: 6px 8px; }
    .task {
      padding: 8px 12px;
      background: var(--vscode-editor-inactiveSelectionBackground);
      border-radius: 4px;
      font-size: 12px;
      margin-bottom: 8px;
    }
    .hint {
      font-size: 11px;
      color: var(--vscode-descriptionForeground);
      margin-top: 12px;
      padding: 8px;
      background: var(--vscode-textBlockQuote-background);
      border-radius: 4px;
    }
  </style>
</head>
<body>
  <div class="header">
    <div class="orb" id="orb"></div>
    <div>
      <div class="title">Jaeger</div>
      <div class="status" id="status">Connecting...</div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Current Task</div>
    <div class="task" id="task">—</div>
  </div>

  <div class="section">
    <div class="section-title">Quick Actions</div>
    <div class="quick-actions">
      <button class="button" onclick="ask('Explain the current file')">Explain</button>
      <button class="button" onclick="ask('Fix any errors in the current file')">Fix</button>
      <button class="button" onclick="ask('Write tests for the current file')">Test</button>
      <button class="button" onclick="ask('Review the current file for improvements')">Review</button>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Open Chat</div>
    <button class="button primary" onclick="openChat()">💬 Open Full Chat</button>
  </div>

  <div class="section">
    <div class="section-title">System</div>
    <button class="button" onclick="checkStatus()">Check Status</button>
  </div>

  <div class="hint">
    💡 Tip: Select code and right-click → "Ask Jaeger" for inline actions.
    The full conversation happens in the chat window.
  </div>

  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const orb = document.getElementById('orb');
    const status = document.getElementById('status');
    const task = document.getElementById('task');

    window.addEventListener('message', event => {
      const { type, state } = event.data;
      if (type === 'state') {
        updateState(state);
      }
    });

    function updateState(state) {
      orb.className = 'orb ' + (state.status || 'idle');
      status.textContent = state.status || 'Unknown';
      task.textContent = state.currentTask || '—';
    }

    function ask(text) {
      vscode.postMessage({ command: 'ask', text });
    }

    function openChat() {
      vscode.postMessage({ command: 'openChat' });
    }

    function checkStatus() {
      vscode.postMessage({ command: 'checkStatus' });
    }
  </script>
</body>
</html>`;
  }
}

function getNonce() {
  let text = '';
  const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}

// ─────────────────────────────────────────────────────────────
// Chat Participant — @jaeger in VS Code Chat
// ─────────────────────────────────────────────────────────────

// Already exists in extension.js — we'll keep it but route through controller

// ─────────────────────────────────────────────────────────────
// Exports
// ─────────────────────────────────────────────────────────────

module.exports = {
  JaegerController,
  JaegerCodeActionProvider,
  JaegerInlineCompletionsProvider,
  JaegerSidebarProvider,
};
