'use strict';
const vscode = require('vscode');
const { randomBytes } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { Gateway } = require('./gateway');
const { Conversation } = require('./conversation');
const { parseProviderModel } = require('./media/presentation');
const commands = require('./commands');
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
  // What the operator has open right now. The active editor stays "active" while the
  // Jaeger panel has focus, so this reflects their file, not the panel.
  // The permission pill: what the agent may do without asking, saved on the instance.
  const sendAutonomy = async mode => {
    try {
      const gw = controller?.gateway || new Gateway(endpoint());
      const result = mode ? await gw.setAutonomy(mode) : await gw.autonomy();
      view?.webview.postMessage({ autonomy: { mode: result.autonomy, options: result.options } });
    } catch (error) { if (mode) throw error; /* reading is best-effort: the pill just stays unknown */ }
  };
  // What the agent's ide_* tools can ask of the editor. Reads are bounded; opening a
  // file only changes what the operator is looking at.
  const ideCall = async (kind, args) => {
    const roots = (vscode.workspace.workspaceFolders || []).map(folder => folder.uri.fsPath);
    const absolute = file => (path.isAbsolute(file) ? file : path.join(roots[0] || '', file));
    const shown = file => { const root = roots.find(r => file.startsWith(r + path.sep)); return root ? file.slice(root.length + 1) : file; };
    if (kind === 'context') return ideContext() || { note: 'Nothing is open in the editor' };
    if (kind === 'open_file') {
      const file = absolute(String(args.path || ''));
      const editor = await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(vscode.Uri.file(file)), { preview: false });
      const line = Number(args.line) > 0 ? Number(args.line) - 1 : -1;
      if (line >= 0) {
        const position = new vscode.Position(Math.min(line, editor.document.lineCount - 1), 0);
        editor.selection = new vscode.Selection(position, position);
        editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
      }
      return { opened: shown(file), line: line >= 0 ? line + 1 : null };
    }
    if (kind === 'diagnostics') {
      const only = args.path ? absolute(String(args.path)) : '';
      const levels = ['error', 'warning', 'info', 'hint'], found = [];
      for (const [uri, list] of vscode.languages.getDiagnostics()) {
        if (uri.scheme !== 'file' || (only && uri.fsPath !== only)) continue;
        for (const item of list) found.push({ path: shown(uri.fsPath), severity: levels[item.severity] || 'info',
          line: item.range.start.line + 1, message: String(item.message).slice(0, 300), source: item.source || '' });
      }
      found.sort((a, b) => levels.indexOf(a.severity) - levels.indexOf(b.severity));
      return { count: found.length, diagnostics: found.slice(0, 60), truncated: found.length > 60 };
    }
    throw new Error(`Unsupported IDE request: ${kind}`);
  };
  const ideContext = () => {
    const editor = vscode.window.activeTextEditor;
    const chosen = editor && !editor.selection.isEmpty ? editor.selection : null;
    const fileTabs = (vscode.window.tabGroups?.all || []).flatMap(group => group.tabs)
      .map(tab => tab.input?.uri).filter(uri => uri?.scheme === 'file').map(uri => uri.fsPath);
    return commands.buildIdeContext({
      folders: (vscode.workspace.workspaceFolders || []).map(folder => folder.uri.fsPath),
      active: editor && editor.document.uri.scheme === 'file' ? {
        path: editor.document.uri.fsPath, language: editor.document.languageId,
        selectionText: chosen ? editor.document.getText(chosen).slice(0, 4001) : '',
        startLine: chosen ? chosen.start.line + 1 : 0, endLine: chosen ? chosen.end.line + 1 : 0,
        cursorLine: editor.selection.active.line + 1,
      } : null,
      openPaths: fileTabs,
    });
  };
  let changes = { files: [] }, wasBusy = false, changeKey = '', changeGeneration = 0, selectedChangeRequest = '';
  const diffDocuments = new Map();
  const changesUrl = () => {
    const sid = controller?.state.session?.session_id;
    const rid = selectedChangeRequest || controller?.workBySession[sid]?.at(-1)?.requestId;
    return sid && rid ? `/v1/sessions/${encodeURIComponent(sid)}/requests/${encodeURIComponent(rid)}/changes` : '';
  };
  async function refreshChanges() {
    const generation = ++changeGeneration, url = changesUrl();
    let next;
    try { next = url ? await controller.gateway.json(url) : { files: [] }; }
    catch (error) { next = { files: [], error: `Change tracking unavailable: ${error.message}` }; }
    if (generation !== changeGeneration || url !== changesUrl()) return;
    changes = next;
    view?.webview.postMessage({ changes });
  }
  context.subscriptions.push(vscode.workspace.registerTextDocumentContentProvider('jaeger-baseline', {
    async provideTextDocumentContent(uri) {
      if (!diffDocuments.has(uri.query)) throw new Error('Reopen this review to reload its snapshots.');
      return diffDocuments.get(uri.query);
    },
  }));
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
    controller = new Conversation(new Gateway(endpoint()), state => {
      if (state.changes) changes = state.changes;
      view?.webview.postMessage(state);
      const key = `${state.session?.session_id || ''}:${state.workTurns?.at(-1)?.requestId || ''}`;
      if (key !== changeKey) selectedChangeRequest = '';
      if ((wasBusy && !state.busy) || key !== changeKey) { changeKey = key; void refreshChanges(); }
      wasBusy = state.busy;
    },
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
        CSS: asset('view.css'), MOTION: asset('motion.css'), SLASH: asset('slash-commands.js'), LOGO: asset('jaeger.svg'), FRAME_QUEUE: asset('frame-queue.js'),
        TIMELINE: asset('timeline.js'), KEYED_RENDERER: asset('keyed-renderer.js'),
        PRESENTATION: asset('presentation.js'),
        DURATION: asset('turn-duration.js'),
        MARKDOWN: asset('markdown.js'), JS: asset('view.js'),
        // May not exist in an unpackaged dev checkout — see THIRD_PARTY_NOTICES.md.
        // A 404 on this URI is expected there; view.js's dynamic import()
        // catches it and falls back to plain-text rendering.
        SMD: asset('vendor/smd.min.js'),
      };
      html = html.replace(/\{\{(CSP|NONCE|CSS|MOTION|SLASH|LOGO|FRAME_QUEUE|TIMELINE|KEYED_RENDERER|PRESENTATION|DURATION|MARKDOWN|JS|SMD)\}\}/g, (_, key) => values[key]);
      view.webview.html = html;
      let selected;
      const messageSubscription = view.webview.onDidReceiveMessage(message => report(async () => {
        if (!message || typeof message.type !== 'string') return;
        if (message.type === 'settings') return settings();
        if (message.type === 'editDraft' && typeof message.text === 'string') {
          const answer = await vscode.window.showWarningMessage('Replace your current draft with this message?', { modal: true }, 'Replace draft');
          if (answer === 'Replace draft') view?.webview.postMessage({ editDraft: message.text });
          return;
        }
        if (message.type === 'ready') { selected = createController(); controller.ideHandler = ideCall; void refreshChanges(); void sendAutonomy(); return controller.refresh(selected); }
        if (message.type === 'turnChanges' && !controller?.state.busy) {
          const turns = controller?.workBySession[controller?.state.session?.session_id] || [];
          if (!turns.some(turn => turn.requestId === message.requestId)) return;
          selectedChangeRequest = message.requestId;
          return refreshChanges();
        }
        if (message.type === 'previewChange' && typeof message.path === 'string') {
          const url = changesUrl();
          if (!url) return;
          const data = await controller.gateway.json(url + '?contents=1');
          if (url !== changesUrl()) return;
          const file = data.files.find(item => item.path === message.path);
          if (file) view?.webview.postMessage({ preview: { ...file, requestId: data.requestId } });
          return;
        }
        if (message.type === 'reviewChanges') {
          let filePath = message.path;
          if (!filePath) filePath = (await vscode.window.showQuickPick(changes.files.map(f => ({ label: path.basename(f.path), description: f.path, path: f.path })), { title: 'Review this turn’s edits' }))?.path;
          if (!filePath) return;
          const data = await controller.gateway.json(changesUrl() + '?contents=1');
          const file = data.files.find(item => item.path === filePath);
          if (!file) throw new Error('Change no longer available. Reload chats to refresh.');
          const token = randomBytes(12).toString('hex');
          const uris = ['before', 'after'].map(side => {
            const key = `${token}:${side}`; diffDocuments.set(key, file[side]);
            return vscode.Uri.from({ scheme: 'jaeger-baseline', path: '/' + path.basename(file.path), query: key });
          });
          while (diffDocuments.size > 100) diffDocuments.delete(diffDocuments.keys().next().value);
          return vscode.commands.executeCommand('vscode.diff', ...uris, `${path.basename(file.path)} — This turn`);
        }
        if (message.type === 'undoChanges') {
          if (controller?.state.busy) throw new Error('Wait for the turn to finish before undoing.');
          const url = changesUrl();
          if (!url) return;
          if (vscode.workspace.textDocuments?.some(doc => doc.isDirty && changes.files.some(f => f.path === doc.uri.fsPath))) throw new Error('Save or discard unsaved editor changes before Undo.');
          const answer = await vscode.window.showWarningMessage('Undo the file edits recorded for this turn?', { modal: true, detail: 'Only recorded files are restored. Undo will refuse if any file has changed since the agent edited it. Backup contents remain in the Gateway state directory.' }, 'Undo edits');
          if (answer !== 'Undo edits' || url !== changesUrl()) return;
          await controller.gateway.json(url + '/undo', {});
          await refreshChanges();
          return;
        }
        if (!controller) return;
        if (message.type === 'home') return controller.refresh(null);
        if (message.type === 'refresh') { void refreshChanges(); return controller.refresh(undefined, true); }
        if (message.type === 'select' && typeof message.id === 'string') {
          if (controller.sending) throw new Error('Wait for request admission before switching.');
          return controller.refresh(message.id);
        }
        if (message.type === 'new') {
          await controller.newSession('New conversation', vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '');
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
          return controller.send(message.text, model, provider, vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '', message.ideContext === false ? null : ideContext());
        }
        // Slash commands that need the Gateway or a file dialog. Each maps to a real
        // capability; the panel never lists one whose backend is missing.
        if (message.type === 'setAutonomy' && typeof message.mode === 'string') return sendAutonomy(message.mode);
        if (message.type === 'rename' && typeof message.title === 'string') {
          const id = controller.state.session?.session_id;
          if (!id) throw new Error('Open a conversation first.');
          const title = message.title.trim();
          if (!title) throw new Error('Give the conversation a name, e.g. /rename Fix the login loop');
          await controller.gateway.rename(id, title.slice(0, 200));
          return controller.refresh(id, true);
        }
        if (message.type === 'exportChat') {
          const session = controller.state.session;
          if (!session?.messages?.length) throw new Error('Nothing to export yet.');
          const folder = vscode.workspace.workspaceFolders?.[0]?.uri;
          const target = await vscode.window.showSaveDialog({
            title: 'Export conversation', filters: { Markdown: ['md'] },
            defaultUri: folder ? vscode.Uri.joinPath(folder, `${commands.slug(session.title)}.md`) : undefined,
          });
          if (!target) return;
          await vscode.workspace.fs.writeFile(target, Buffer.from(commands.exportMarkdown(session), 'utf8'));
          view?.webview.postMessage({ info: { title: 'Exported', lines: [target.fsPath] } });
          return;
        }
        if (message.type === 'info' && ['status', 'skills', 'agent'].includes(message.what)) {
          let title, lines;
          if (message.what === 'status') {
            const version = await controller.gateway.json('/version');
            title = 'Status';
            lines = commands.statusLines({ version, endpoint: controller.gateway.url, session: controller.state.session,
              model: configuredModel() || controller.state.session?.metadata?.model || '' });
          } else if (message.what === 'skills') {
            const query = String(message.query || '').trim().slice(0, 60);
            const found = await controller.gateway.skills(query);
            title = 'Skills'; lines = commands.skillLines(found.skills, query);
          } else {
            title = 'Agents and tasks'; lines = commands.taskLines(await controller.gateway.tasks());
          }
          view?.webview.postMessage({ info: { title, lines } });
          return;
        }
        if (message.type === 'cancelBackgroundTask' && typeof message.id === 'string') return controller.cancelBackgroundTask(message.id);
        if (message.type === 'cancel') return controller.cancel();
        if (message.type === 'approve' && typeof message.id === 'string' && typeof message.approved === 'boolean') return controller.approve(message.id, message.approved);
        if (message.type === 'attach') {
          const picked = await vscode.window.showOpenDialog({
            canSelectMany: true, openLabel: 'Attach to conversation',
            title: 'Attach a file from your Jaeger workspace',
          });
          if (picked?.length && !controller.state.session) await controller.newSession('New conversation', vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '');
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
