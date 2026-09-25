'use strict';
// Tests for the extension.js webview-message → Gateway admission wire.
// vscode is not available outside the extension host; we inject a minimal mock
// via the module cache before requiring extension.js. No new dependencies.
const { test, before } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');

// ---- vscode mock ---------------------------------------------------------
let jaegerModelSetting = 'settings-model';
const configChangeListeners = [];
const mockVscode = {
  window: {
    createOutputChannel: () => ({ appendLine: () => {}, show: () => {}, dispose: () => {} }),
    showInputBox: async () => 'Test',
    showWorkspaceFolderPick: async () => ({ uri: { fsPath: '/workspace/two' } }),
    registerWebviewViewProvider: () => ({ dispose: () => {} }),
  },
  commands: { registerCommand: () => ({ dispose: () => {} }), executeCommand: async () => {} },
  workspace: {
    registerTextDocumentContentProvider: () => ({ dispose() {} }),
    getConfiguration: () => ({ get: (key) => key === 'model' ? jaegerModelSetting : '' }),
    onDidChangeConfiguration: (fn) => { configChangeListeners.push(fn); return { dispose: () => {} }; },
    workspaceFolders: [
      { uri: { fsPath: '/workspace/one' } },
      { uri: { fsPath: '/workspace/two' } },
    ],
  },
  Uri: { joinPath: (base, ...parts) => ({ toString: () => [base?.toString(), ...parts].join('/') }) },
  env: { clipboard: { writeText: async () => {} } },
};

// Patch before any require so extension.js picks up the mocks.
const CONTRACT_KEY = '__mock_contract__';
const origResolve = Module._resolveFilename.bind(Module);
Module._resolveFilename = (req, parent, isMain, opts) => {
  if (req === 'vscode') return '__mock_vscode__';
  // contract.json is generated outside the checkout and does not exist in tests.
  if (req === './contract.json' || req.endsWith('/contract.json')) return CONTRACT_KEY;
  return origResolve(req, parent, isMain, opts);
};
require.cache['__mock_vscode__'] = { id: '__mock_vscode__', filename: '__mock_vscode__', loaded: true, exports: mockVscode };
require.cache[CONTRACT_KEY] = { id: CONTRACT_KEY, filename: CONTRACT_KEY, loaded: true,
  exports: { gatewayUrl: 'http://127.0.0.1:8810' } };

// ---- Stub gateway --------------------------------------------------------
// Records the most-recent admission body. Injected into the module cache so
// extension.js's `new Gateway(url)` returns this stub, not a real HTTP client.
const stubGateway = { sent: null };
class GatewayStub {
  constructor(url) { this.url = url; stubGateway.instance = this; }
  async json() { return { component: 'jaeger-gateway', service: 'jaeger-gateway' }; }
  async sessions() { return { sessions: [] }; }
  async session(id) { return { session_id: id, title: id, status: 'idle', messages: [] }; }
  async approvals() { return { approvals: [] }; }
  async models() { return { providers: [] }; }
  async send(sid, body) { stubGateway.sent = body; return { start_event_id: 1, status: 'running' }; }
  async receipt() { return { status: 'running' }; }
  async *events() {}
  async cancel() { return {}; }
}
class GatewayErrorStub extends Error {}
const gwPath = require.resolve('../gateway');
require.cache[gwPath] = { id: gwPath, filename: gwPath, loaded: true,
  exports: { Gateway: GatewayStub, GatewayError: GatewayErrorStub, localEndpoint: u => u, decodeSSE: async function* () {} } };

// ---- Load extension ------------------------------------------------------
const { activate } = require('../extension');

// ---- Test harness ---------------------------------------------------------
const waitFor = async predicate => {
  const end = Date.now() + 5000;
  while (!predicate()) { if (Date.now() > end) throw new Error('Timed out'); await new Promise(r => setTimeout(r, 10)); }
};

function makeContext() {
  return {
    subscriptions: { push: () => {} },
    extensionUri: { toString: () => 'ext' },
    extensionPath: path.join(__dirname, '..'),
    workspaceState: { get: () => ({}), update: async () => {} },
  };
}

// Activate the extension and return a handle to simulate webview messages.
function wireExtension() {
  stubGateway.sent = null;
  const posted = [];
  let msgHandler, disposeHandler, messageDisposed = false;
  const mockView = {
    webview: {
      options: {}, html: '',
      cspSource: 'csp',
      asWebviewUri: u => ({ toString: () => String(u) }),
      onDidReceiveMessage: fn => { msgHandler = fn; return { dispose: () => { messageDisposed = true; msgHandler = undefined; } }; },
      postMessage: msg => posted.push(msg),
    },
    onDidDispose: fn => { disposeHandler = fn; return { dispose: () => {} }; },
  };
  const context = makeContext();
  activate(context);
  // Trigger resolveWebviewView — captured by registerWebviewViewProvider.
  // Extension registers via subscriptions.push; we call it through the provider
  // object captured during registerWebviewViewProvider mock.
  mockVscode.window.registerWebviewViewProvider = (id, provider) => {
    provider.resolveWebviewView(mockView);
    return { dispose: () => {} };
  };
  // Re-activate to pick up the updated mock
  activate(context);
  const send = msg => msgHandler && msgHandler(msg);
  return { send, posted, gateway: stubGateway, dispose: () => disposeHandler?.(), messageDisposed: () => messageDisposed };
}

// ---- Tests ---------------------------------------------------------------

test('disposing a view releases its message listener', () => {
  const wired = wireExtension();
  assert.equal(wired.messageDisposed(), false);
  wired.dispose();
  assert.equal(wired.messageDisposed(), true);
});

test('explicit workspace selection reaches the Gateway admission body', async () => {
  const { send, gateway, posted } = wireExtension();
  send({ type: 'ready' });
  await waitFor(() => gateway.instance !== undefined);
  gateway.instance.sessions = async () => ({ sessions: [{ session_id: 'ws', title: 'T', status: 'idle', messages: [] }] });
  gateway.instance.session = async id => ({ session_id: id, title: 'T', status: 'idle', messages: [] });
  send({ type: 'select', id: 'ws' });
  await new Promise(r => setTimeout(r, 50));

  send({ type: 'selectWorkspace' });
  await waitFor(() => posted.some(message => message.selectedWorkspace === '/workspace/two'));
  send({ type: 'send', text: 'hello', model: '' });
  await waitFor(() => gateway.sent !== null);
  assert.equal(gateway.sent.workspace, '/workspace/two', 'selected workspace must be frozen into admission');
});

test('model "config" → jaeger.model setting reaches admission body', async () => {
  jaegerModelSetting = 'my-static-model';
  const { send, gateway } = wireExtension();
  send({ type: 'ready' });
  await waitFor(() => gateway.instance !== undefined);
  // Simulate a connected session so send() goes through.
  gateway.instance.sessions = async () => ({ sessions: [{ session_id: 'sid', title: 'T', status: 'idle', messages: [] }] });
  gateway.instance.session = async id => ({ session_id: id, title: 'T', status: 'idle', messages: [] });
  send({ type: 'select', id: 'sid' });
  await new Promise(r => setTimeout(r, 50));
  send({ type: 'send', text: 'hello', model: 'config' });
  await waitFor(() => gateway.sent !== null);
  assert.equal(gateway.sent.model, 'my-static-model', '"config" must use the jaeger.model setting');
  assert.ok(!('provider' in gateway.sent), 'no provider for a setting-only model string');
});

test('model "" → no model override (keep session/Gateway selection)', async () => {
  jaegerModelSetting = 'my-static-model';
  const { send, gateway } = wireExtension();
  send({ type: 'ready' });
  await waitFor(() => gateway.instance !== undefined);
  gateway.instance.sessions = async () => ({ sessions: [{ session_id: 'sid2', title: 'T', status: 'idle', messages: [] }] });
  gateway.instance.session = async id => ({ session_id: id, title: 'T', status: 'idle', messages: [] });
  send({ type: 'select', id: 'sid2' });
  await new Promise(r => setTimeout(r, 50));
  send({ type: 'send', text: 'hello', model: '' });
  await waitFor(() => gateway.sent !== null);
  assert.ok(!('model' in gateway.sent), 'empty model must produce no model field in admission');
});

test('model "openai::gpt-4" → provider and model both reach admission body', async () => {
  const { send, gateway } = wireExtension();
  send({ type: 'ready' });
  await waitFor(() => gateway.instance !== undefined);
  gateway.instance.sessions = async () => ({ sessions: [{ session_id: 's3', title: 'T', status: 'idle', messages: [] }] });
  gateway.instance.session = async id => ({ session_id: id, title: 'T', status: 'idle', messages: [] });
  send({ type: 'select', id: 's3' });
  await new Promise(r => setTimeout(r, 50));
  send({ type: 'send', text: 'hello', model: 'openai::gpt-4' });
  await waitFor(() => gateway.sent !== null);
  assert.equal(gateway.sent.model, 'gpt-4');
  assert.equal(gateway.sent.provider, 'openai');
});

test('duplicate model-id across providers stays distinct: anthropic::gpt-4 ≠ openai::gpt-4', async () => {
  const { send: send1, gateway: gw1 } = wireExtension();
  send1({ type: 'ready' });
  await waitFor(() => gw1.instance !== undefined);
  gw1.instance.sessions = async () => ({ sessions: [{ session_id: 'sa', title: 'T', status: 'idle', messages: [] }] });
  gw1.instance.session = async id => ({ session_id: id, title: 'T', status: 'idle', messages: [] });
  send1({ type: 'select', id: 'sa' });
  await new Promise(r => setTimeout(r, 50));

  send1({ type: 'send', text: 'q', model: 'anthropic::gpt-4' });
  await waitFor(() => gw1.sent !== null);
  assert.equal(gw1.sent.provider, 'anthropic');
  assert.equal(gw1.sent.model, 'gpt-4');

  gw1.sent = null;
  send1({ type: 'send', text: 'q', model: 'openai::gpt-4' });
  // send is blocked while busy — verify the distinction at the parse level
  const { parseProviderModel } = require('../media/presentation');
  assert.notDeepEqual(parseProviderModel('anthropic::gpt-4'), parseProviderModel('openai::gpt-4'));
  assert.equal(parseProviderModel('anthropic::gpt-4').provider, 'anthropic');
  assert.equal(parseProviderModel('openai::gpt-4').provider, 'openai');
});

test('explicit "refresh" message triggers catalog reload on reconnect', async () => {
  let modelCalls = 0;
  const { send, gateway } = wireExtension();
  gateway.instance = undefined;
  send({ type: 'ready' });
  await waitFor(() => gateway.instance !== undefined);
  gateway.instance.models = async () => { modelCalls++; return { providers: [] }; };
  // First refresh (implicit from 'ready')
  await new Promise(r => setTimeout(r, 50));
  const callsAfterReady = modelCalls;
  // Explicit refresh
  send({ type: 'refresh' });
  await new Promise(r => setTimeout(r, 80));
  assert.ok(modelCalls > callsAfterReady, 'explicit refresh must reload the catalog');
});

test('initial state posted to webview includes configuredModel', async () => {
  jaegerModelSetting = 'cfg-model-x';
  const { send, posted } = wireExtension();
  // createController() posts the connecting state when the 'ready' message arrives.
  send({ type: 'ready' });
  await waitFor(() => posted.some(m => m.status === 'Connecting…'));
  const connecting = posted.find(m => m.status === 'Connecting…');
  assert.ok(connecting, 'extension must post an initial connecting state');
  assert.equal(connecting.configuredModel, 'cfg-model-x', 'configuredModel must be in the initial state');
});
