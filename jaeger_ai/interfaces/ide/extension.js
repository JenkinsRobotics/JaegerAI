/**
 * Jaeger VS Code Extension — Controller (v0.2.0)
 *
 * ARCHITECTURE: Centralized Brain + Thin Clients
 * ────────────────────────────────────────────────
 * The Apple-Native Web UI is the ONE chat interface.
 * This extension is a CONTROLLER — it sends context and
 * quick actions to the Gateway, shows agent status,
 * and opens the chat when you need to see/talk.
 *
 * What this extension does:
 * - Status bar: Shows what Jaeger is doing (idle/thinking/working)
 * - Sidebar: Agent state, quick actions, recent tasks
 * - Code actions: Right-click → "Ask Jaeger" (explain, fix, test, refactor)
 * - @jaeger: Chat participant that routes to the agent
 * - Opens main chat: Click status bar or press Cmd+Shift+J
 *
 * What this extension does NOT do:
 * - No chat UI (the web UI is the chat)
 * - No conversation state (Gateway owns it)
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

// ─────────────────────────────────────────────────────────────
// Activation
// ─────────────────────────────────────────────────────────────

/** @type {JaegerController | null} */
let controller = null;

/** @type {vscode.OutputChannel} */
let output;

function activate(context) {
  output = vscode.window.createOutputChannel('Jaeger');
  context.subscriptions.push(output);
  output.appendLine('[jaeger] Extension activating (Controller mode)...');

  // Create gateway client
  const gateway = createGatewayClient();

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
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.open', () => {
      vscode.commands.executeCommand('jaeger.controller.focus');
    })
  );

  // Settings
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.settings', () => {
      vscode.commands.executeCommand('workbench.action.openSettings', 'jaeger');
    })
  );

  // Set caller token (secure storage)
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.setToken', async () => {
      const token = await vscode.window.showInputBox({
        prompt: 'Gateway Caller Token',
        placeHolder: 'Paste your token (stored in OS SecretStorage)',
        password: true,
        ignoreFocusOut: true,
      });
      if (token) {
        await context.secrets.store('jaeger.callerToken', token);
        vscode.window.showInformationMessage('Jaeger: Token saved securely.');
      }
    })
  );

  // Select model
  context.subscriptions.push(
    vscode.commands.registerCommand('jaeger.selectModel', async () => {
      try {
        const models = await gateway.models();
        const items = (models.models || models || []).map(m => ({
          label: m.name || m.id,
          description: m.provider || m.type,
          detail: m.id,
        }));
        const picked = await vscode.window.showQuickPick(items, {
          placeHolder: 'Select default model',
        });
        if (picked) {
          await vscode.workspace.getConfiguration('jaeger').update('model', picked.detail, true);
          vscode.window.showInformationMessage(`Jaeger: Model set to ${picked.label}`);
        }
      } catch (error) {
        vscode.window.showErrorMessage(`Failed to load models: ${error.message}`);
      }
    })
  );

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

  const chatParticipant = vscode.chat.createChatParticipant('jaeger.chatParticipant', async (request, context, stream, token) => {
    output.appendLine(`[jaeger] @jaeger invoked: ${request.command || 'message'}`);

    try {
      // Handle slash commands locally
      if (request.command === 'status') {
        const health = await gateway.json('/health');
        stream.markdown(`**Jaeger Gateway Status**\n\n` +
          `- Status: ${health.status}\n` +
          `- Version: ${health.version}\n` +
          `- Model: ${health.model || 'default'}\n` +
          `- Endpoint: ${gateway.url}\n\n` +
          `[Open Full Chat](command:jaeger.openChat)`);
        return;
      }

      if (request.command === 'verify') {
        stream.progress('Running verification suite...');
        // Delegate to controller's runTests
        await controller.runTests();
        stream.markdown('Verification request sent. See chat for results.');
        return { metadata: { command: 'verify' } };
      }

      if (request.command === 'explain') {
        await controller.explainCode();
        stream.markdown('Explanation request sent. Opening chat...');
        return { metadata: { command: 'explain' } };
      }

      if (request.command === 'fix') {
        await controller.fixCode();
        stream.markdown('Fix request sent. Opening chat...');
        return { metadata: { command: 'fix' } };
      }

      if (request.command === 'test') {
        await controller.writeTests();
        stream.markdown('Test generation request sent. Opening chat...');
        return { metadata: { command: 'test' } };
      }

      // Regular message — send to agent
      const prompt = request.prompt;
      if (!prompt) return;

      stream.progress('Sending to Jaeger...');
      await controller.ask(prompt, {
        includeCode: true,
        chatRequest: request,
      });

      stream.markdown(`Request sent to Jaeger. [Open chat to see the response](command:jaeger.openChat)`);

      return { metadata: { command: request.command } };
    } catch (error) {
      stream.markdown(`**Error:** ${error.message}\n\nIs the Gateway running? Try \`jaeger gateway daemon\`.`);
      return { metadata: { error: error.message } };
    }
  });

  chatParticipant.iconPath = vscode.Uri.joinPath(context.extensionUri, 'media', 'jaeger.svg');
  context.subscriptions.push(chatParticipant);

  // ─────────────────────────────────────────────────────────
  // Status bar click → open chat
  // ─────────────────────────────────────────────────────────

  // Already handled by controller's status bar item

  output.appendLine('[jaeger] Extension activated successfully.');
  output.appendLine('[jaeger] Chat UI: Open with Cmd+Shift+J or click status bar.');

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
    token: async (caller) => {
      // Try secure storage first
      const stored = await vscode.workspace.getConfiguration('jaeger').get('callerToken');
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
