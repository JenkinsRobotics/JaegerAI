/**
 * Jaeger VS Code Extension — Controller (v0.2.0)
 *
 * ARCHITECTURE: Centralized Brain + Thin Clients
 * ────────────────────────────────────────────────
 * The Gateway owns conversations. This extension is a controller
 * (context, quick actions, agent status) plus the in-IDE chat.
 *
 * What this extension does:
 * - Status bar: Shows what Jaeger is doing (idle/thinking/working)
 * - Sidebar: Agent state, quick actions, recent tasks
 * - Code actions: Right-click → "Ask Jaeger" (explain, fix, test, refactor)
 * - Opens the web chat: Click status bar or press Cmd+Shift+J
 * - In-IDE chat: the Chat view (chat-panel.js + media/index.html on
 *   conversation.js) and a streaming @jaeger with Sources and follow-ups
 *
 * What this extension does NOT do:
 * - No model calls (Gateway + Ollama Cloud handle that)
 */

'use strict';

const vscode = require('vscode');
const { Gateway, GatewayError, callerToken } = require('./gateway');
const {
  JaegerController,
  JaegerCodeActionProvider,
  JaegerInlineCompletionsProvider,
  JaegerSidebarProvider,
} = require('./controller');
const { registerJaegerLanguageModelProvider } = require('./language-model-provider');
const chatPanel = require('./chat-panel');

// Commands the controller below registers itself. The chat panel owns the rest:
// jaeger.open (focus the in-IDE chat), jaeger.setToken (scoped per endpoint),
// jaeger.selectModel (provider::model, decoded by every admission path),
// the conversation commands and the one streaming @jaeger participant.
const CONTROLLER_OWNED = ['jaeger.settings'];

// ─────────────────────────────────────────────────────────────
// Activation
// ─────────────────────────────────────────────────────────────

/** @type {JaegerController | null} */
let controller = null;

/** @type {vscode.OutputChannel} */
let output;

function isJaegerDesktop() {
  return /^(?:Jaeger(?: Desktop)?|VS Code Chat)$/i.test(String(vscode.env?.appName || '').trim());
}

function activate(context) {
  output = vscode.window.createOutputChannel('Jaeger');
  context.subscriptions.push(output);
  output.appendLine('[jaeger] Extension activating (Controller mode)...');
  const nativeChat = isJaegerDesktop();
  void vscode.commands.executeCommand('setContext', 'jaeger.nativeChat', nativeChat);

  // Create gateway client
  const gateway = createGatewayClient();

  // Make the Gateway a first-class native model for Jaeger Desktop's built-in chat.
  registerJaegerLanguageModelProvider(vscode, context, gateway, output);

  // Create controller
  controller = new JaegerController(context, gateway);
  controller.activate();
  context.subscriptions.push(controller);

  // ─────────────────────────────────────────────────────────
  // Commands
  // ─────────────────────────────────────────────────────────

  // Open main chat (Apple-Native UI)
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.openChat', async () => {
      output.appendLine('[jaeger] Opening chat...');
      await controller.openChat();
    })
  );

  // Quick ask (prompts for input)
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.ask', async () => {
      const input = await vscode.window.showInputBox({
        prompt: 'Ask Jaeger',
        placeHolder: 'What do you want to know or do?',
        ignoreFocusOut: true,
      });
      if (input) {
        await controller.ask(input);
      }
    })
  );

  // Explain selected code
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.explainCode', async () => {
      output.appendLine('[jaeger] Explain code action...');
      await controller.explainCode();
    })
  );

  // Fix selected code
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.fixCode', async () => {
      output.appendLine('[jaeger] Fix code action...');
      await controller.fixCode();
    })
  );

  // Write tests for selected code
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.writeTests', async () => {
      output.appendLine('[jaeger] Write tests action...');
      await controller.writeTests();
    })
  );

  // Refactor selected code
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.refactorCode', async () => {
      output.appendLine('[jaeger] Refactor code action...');
      await controller.refactorCode();
    })
  );

  // Document selected code
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.documentCode', async () => {
      output.appendLine('[jaeger] Document code action...');
      await controller.documentCode();
    })
  );

  // Review selected code
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.reviewCode', async () => {
      output.appendLine('[jaeger] Review code action...');
      await controller.reviewCode();
    })
  );

  // Run project tests
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.runTests', async () => {
      output.appendLine('[jaeger] Run tests action...');
      await controller.runTests();
    })
  );

  // Check agent status
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.checkStatus', async () => {
      await controller.checkStatus();
    })
  );

  // Open controller panel

  // Settings
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.settings', () => {
      vscode.commands.executeCommand('workbench.action.openSettings', 'jaeger');
    })
  );

  // Set caller token (secure storage)

  // Select model

  // Implement TODO (from inline completion)
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.implementTodo', async (document, position, textBefore) => {
      const line = document.lineAt(position.line);
      await controller.ask(
        `Implement this TODO in ${document.uri.fsPath}:\n\n${line.text}\n\nProvide the complete implementation.`
      );
    })
  );

  // ─────────────────────────────────────────────────────────
  // Providers
  // ─────────────────────────────────────────────────────────

  // Code actions (right-click menu)
  context.subscriptions.push(
    vscode.languages.registerCodeActionsProvider(
      { scheme: 'file' },
      new JaegerCodeActionProvider(controller),
      {
        providedCodeActionKinds: [
          vscode.CodeActionKind.QuickFix,
          vscode.CodeActionKind.Refactor,
          vscode.CodeActionKind.RefactorRewrite,
          vscode.CodeActionKind.RefactorExtract,
        ],
      }
    )
  );

  // Inline completions (ghost text)
  context.subscriptions.push(
    vscode.languages.registerInlineCompletionItemProvider(
      { scheme: 'file' },
      new JaegerInlineCompletionsProvider(controller)
    )
  );

  // Sidebar view (agent status, not chat)
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      'jaeger.controller',
      new JaegerSidebarProvider(controller),
      { webviewOptions: { retainContextWhenHidden: true } }
    )
  );

  // ─────────────────────────────────────────────────────────
  // Chat Participant (@jaeger)
  // ─────────────────────────────────────────────────────────

  // The in-IDE chat: the conversation panel (media/index.html + view.js on
  // conversation.js) and the streaming @jaeger participant (native-turn.js).
  chatPanel.activate(context, { skip: CONTROLLER_OWNED, output, nativeOnly: nativeChat });

  // ─────────────────────────────────────────────────────────
  // Status bar click → open chat
  // ─────────────────────────────────────────────────────────

  // Already handled by controller's status bar item

  output.appendLine('[jaeger] Extension activated successfully.');
  output.appendLine(`[jaeger] Chat UI: ${nativeChat ? 'VS Code native Chat' : 'Jaeger conversation panel'}.`);

  return {
    controller,
    getGateway: () => gateway,
  };
}

function deactivate() {
  output?.appendLine('[jaeger] Extension deactivating...');
  controller?.dispose();
  controller = null;
}

// ─────────────────────────────────────────────────────────────
// Gateway Client Factory
// ─────────────────────────────────────────────────────────────

function createGatewayClient() {
  const config = vscode.workspace.getConfiguration('jaeger');
  const url = config.get('gatewayUrl') || contract.gatewayUrl;

  return new Gateway(url, {
    token: (caller) => {
      // Gateway.auth() is synchronous; return the configured token itself.
      const stored = vscode.workspace.getConfiguration('jaeger').get('callerToken');
      if (stored) return stored;
      // Fall back to keychain/file
      return callerToken(caller);
    },
    nativeLoopback: true,
  });
}

// Packaged builds get contract.json (gatewayUrl) generated from
// jaeger_ai/contract/ports.py; this is only the unpackaged default.
let contract = { gatewayUrl: 'http://127.0.0.1:33418' };
try { contract = require('./contract.json'); } catch (_) {}

// ─────────────────────────────────────────────────────────────
// Exports
// ─────────────────────────────────────────────────────────────

module.exports = { activate, deactivate };
