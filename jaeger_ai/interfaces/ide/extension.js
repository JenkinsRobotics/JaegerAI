'use strict';
const vscode = require('vscode');
const { randomBytes } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { Gateway } = require('./gateway');
const { Conversation } = require('./conversation');
const { parseProviderModel } = require('./media/presentation');
let contract = { gatewayUrl: 'http://127.0.0.1:8810' };
try { contract = require('./contract.json'); } catch (_) {}

// Sniffed from the extension, not the filesystem: this list only decides
// what the Gateway's attachment record says the file is, it never gates
// which files can be picked. Unknown extensions fall back honestly to
// application/octet-stream rather than guessing.
const MIME_BY_EXTENSION = {
  '.txt': 'text/plain', '.md': 'text/markdown', '.json': 'application/json',
  '.csv': 'text/csv', '.py': 'text/x-python', '.js': 'text/javascript',
  '.ts': 'text/typescript', '.html': 'text/html', '.css': 'text/css',
  '.yaml': 'application/yaml', '.yml': 'application/yaml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
  '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml',
  '.pdf': 'application/pdf',
};

function activate(context) {
  const output = vscode.window.createOutputChannel('Jaeger'); context.subscriptions.push(output);
  let view, controller;
  const storageKey = () => `connection:${endpoint()}`;
  const endpoint = () => vscode.workspace.getConfiguration('jaeger').get('gatewayUrl') || contract.gatewayUrl;
  const settings = () => vscode.commands.executeCommand('workbench.action.openSettings', '@ext:jenkins-robotics.jaeger-ide');
  const configuredModel = () => vscode.workspace.getConfiguration('jaeger').get('model') || '';
  function createController() {
    controller?.dispose();
    controller = undefined;
    view?.webview.postMessage({ connected: false, busy: false, session: null, sessions: [], text: '',
      reasoning: '', activity: [], approvals: [], staged: [], models: null, modelsError: null,
      status: 'Connecting…', error: '', configuredModel: configuredModel() });
    const key = storageKey(), restored = context.workspaceState.get(key, {});
    controller = new Conversation(new Gateway(endpoint()), state => view?.webview.postMessage(state),
      state => context.workspaceState.update(key, state), restored);
    return restored.selected;
  }
  async function report(action) {
    try { await action(); } catch (error) {
      output.appendLine(`${new Date().toISOString()} ${error.message}`);
      view?.webview.postMessage({ error: error.message });
    }
  }
  const provider = {
    resolveWebviewView(resolved) {
      view = resolved;
      const media = vscode.Uri.joinPath(context.extensionUri, 'media');
      view.webview.options = { enableScripts: true, localResourceRoots: [media] };
      const nonce = randomBytes(24).toString('hex');
      let html = fs.readFileSync(path.join(context.extensionPath, 'media', 'index.html'), 'utf8');
      const asset = name => view.webview.asWebviewUri(vscode.Uri.joinPath(media, name)).toString();
      const values = {
        CSP: view.webview.cspSource, NONCE: nonce,
        CSS: asset('view.css'), FRAME_QUEUE: asset('frame-queue.js'),
        TIMELINE: asset('timeline.js'), KEYED_RENDERER: asset('keyed-renderer.js'),
        PRESENTATION: asset('presentation.js'),
        MARKDOWN: asset('markdown.js'), JS: asset('view.js'),
        // May not exist in an unpackaged dev checkout — see THIRD_PARTY_NOTICES.md.
        // A 404 on this URI is expected there; view.js's dynamic import()
        // catches it and falls back to plain-text rendering.
        SMD: asset('vendor/smd.min.js'),
      };
      html = html.replace(/\{\{(CSP|NONCE|CSS|FRAME_QUEUE|TIMELINE|KEYED_RENDERER|PRESENTATION|MARKDOWN|JS|SMD)\}\}/g, (_, key) => values[key]);
      view.webview.html = html;
      let selected;
      const messageSubscription = view.webview.onDidReceiveMessage(message => report(async () => {
        if (!message || typeof message.type !== 'string') return;
        if (message.type === 'settings') return settings();
        if (message.type === 'ready') { selected = createController(); return controller.refresh(selected); }
        if (!controller) return;
        if (message.type === 'refresh') return controller.refresh(undefined, true);
        if (message.type === 'select' && typeof message.id === 'string') {
          if (controller.sending) throw new Error('Wait for request admission before switching.');
          return controller.refresh(message.id);
        }
        if (message.type === 'new') {
          const title = await vscode.window.showInputBox({ prompt: 'Conversation focus', placeHolder: 'Project planning, everyday work…', value: 'New conversation' });
          if (title !== undefined) await controller.newSession(title, vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '');
        }
        if (message.type === 'send' && typeof message.text === 'string') {
          // '' = keep session/Gateway selection (no model field in admission).
          // 'config' = use the static jaeger.model setting (shown honestly in picker).
          // 'provider::model' = explicit catalog choice; parsed via shared helper.
          let model = '', provider = '';
          if (message.model === 'config') {
            model = configuredModel();
          } else if (typeof message.model === 'string' && message.model) {
            ({ model, provider } = parseProviderModel(message.model));
          }
          return controller.send(message.text, model, provider);
        }
        if (message.type === 'cancel') return controller.cancel();
        if (message.type === 'approve' && typeof message.id === 'string' && typeof message.approved === 'boolean') return controller.approve(message.id, message.approved);
        if (message.type === 'attach') {
          const picked = await vscode.window.showOpenDialog({
            canSelectMany: true, openLabel: 'Attach to conversation',
            title: 'Attach a file from your Jaeger workspace',
          });
          for (const uri of picked || []) {
            const filePath = uri.fsPath, ext = path.extname(filePath).toLowerCase();
            let size = 0;
            try { size = fs.statSync(filePath).size; } catch { /* let the Gateway's own check report it */ }
            // eslint-disable-next-line no-await-in-loop -- attachments register one at a time, in the order picked
            await controller.addAttachment({
              path: filePath, name: path.basename(filePath),
              mime: MIME_BY_EXTENSION[ext] || 'application/octet-stream', size,
            });
          }
          return;
        }
        if (message.type === 'removeAttachment' && typeof message.id === 'string') {
          return controller.removeStagedAttachment(message.id);
        }
        if (message.type === 'copy' && typeof message.text === 'string') {
          return vscode.env.clipboard.writeText(message.text);
        }
      }));
      view.onDidDispose(() => {
        messageSubscription.dispose();
        controller?.dispose();
        view = undefined;
      }, undefined, context.subscriptions);
    }
  };
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider('jaeger.conversation', provider, { webviewOptions: { retainContextWhenHidden: true } }),
    vscode.commands.registerCommand('jaeger.open', () => vscode.commands.executeCommand('jaeger.conversation.focus')),
    vscode.commands.registerCommand('jaeger.settings', settings),
    vscode.commands.registerCommand('jaeger.diagnostics', () => report(async () => {
      const gw = new Gateway(endpoint()), version = await gw.json('/version');
      output.appendLine(JSON.stringify({ endpoint: gw.url, version, selected: controller?.state.session?.session_id || null }, null, 2));
      output.show(true);
    })),
    vscode.workspace.onDidChangeConfiguration(event => {
      if (event.affectsConfiguration('jaeger.gatewayUrl') && view) report(async () => {
        const selected = createController(); await controller.refresh(selected);
      });
      if (event.affectsConfiguration('jaeger.model') && view) {
        view.webview.postMessage({ configuredModel: configuredModel() });
      }
    }),
    { dispose: () => controller?.dispose() },
  );
}
module.exports = { activate };
