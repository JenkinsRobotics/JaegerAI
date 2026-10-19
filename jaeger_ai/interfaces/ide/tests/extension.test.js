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
let copiedText = null;
const configChangeListeners = [];
const registeredCommands = new Map();
const chatParticipants = new Map();
let chooseItem = items => items[0];
let catalog = { providers: [] };
const mockVscode = {
  ConfigurationTarget: { Global: 1 },
  RelativePattern: class { constructor(base, pattern) { this.base = base; this.pattern = pattern; } },
  languages: { getDiagnostics: () => [] },
  window: {
    createOutputChannel: () => ({ appendLine: () => {}, show: () => {}, dispose: () => {} }),
    showInputBox: async () => 'Test',
    showWorkspaceFolderPick: async () => ({ uri: { fsPath: '/workspace/two' } }),
    showQuickPick: async items => chooseItem(items),
    showInformationMessage: () => {},
    showErrorMessage: () => {},
    registerWebviewViewProvider: () => ({ dispose: () => {} }),
  },
  commands: { registerCommand: (id, fn) => { registeredCommands.set(id, fn); return { dispose() {} }; }, executeCommand: async () => {} },
  chat: { createChatParticipant: (id, handler) => { chatParticipants.set(id, handler); return { dispose() {} }; } },
  workspace: {
    registerTextDocumentContentProvider: () => ({ dispose() {} }),
    getConfiguration: () => ({
      get: key => key === 'model' ? jaegerModelSetting : '',
      inspect: () => ({ globalValue: undefined, defaultValue: undefined }),
      update: async (key, value, target) => {
        assert.equal(key, 'model');
        assert.equal(target, mockVscode.ConfigurationTarget.Global);
        jaegerModelSetting = value;
      },
    }),
    onDidChangeConfiguration: (fn) => { configChangeListeners.push(fn); return { dispose: () => {} }; },
    findFiles: async () => [
      { fsPath: '/workspace/one/src/main.py' },
      { fsPath: '/workspace/one/docs/readme.md' },
    ],
    workspaceFolders: [
      { uri: { fsPath: '/workspace/one' } },
      { uri: { fsPath: '/workspace/two' } },
    ],
  },
  Uri: { joinPath: (base, ...parts) => ({ toString: () => [base?.toString(), ...parts].join('/') }) },
  env: { clipboard: { writeText: async text => { copiedText = text; } } },
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
  exports: { gatewayUrl: 'http://127.0.0.1:33418' } };

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
  async models() { return catalog; }
  async queueAdd(sid, body) { stubGateway.queued = { sid, body }; return { status: 'queued' }; }
  async queue() { return { items: [] }; }
  async send(sid, body) { stubGateway.sent = body; return { start_event_id: 1, status: 'running' }; }
  async addAttachment() { return { attachment_id: 'mention-attachment', original_filename: 'main.py' }; }
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
    globalStorageUri: { fsPath: '/tmp/jaeger-extension-global-storage-test' },
    workspaceState: { get: () => ({}), update: async () => {} },
  };
}

// Activate the extension and return a handle to simulate webview messages.
function wireExtension(options = {}) {
  stubGateway.sent = null;
  stubGateway.queued = null;
  catalog = options.catalog || { providers: [
    { id: 'fixture', reachable: true, models: [{ id: 'my-static-model', available: true }] },
    ...['openai', 'anthropic'].map(id => ({ id, reachable: true, models: [{ id: 'gpt-4', available: true }] })),
  ] };
  chooseItem = items => items[0];
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

test('native chat participant uses one Gateway-owned session across turns', async () => {
  const wired = wireExtension();
  wired.send({ type: 'ready' });
  await waitFor(() => wired.gateway.instance !== undefined);
  const handler = chatParticipants.get('jaeger.chatParticipant');
  assert.equal(typeof handler, 'function');
  const gateway = wired.gateway.instance;
  const createdSessions = [];
  gateway.create = async body => {
    createdSessions.push(body);
    return { session_id: body.session_id };
  };
  gateway.send = async (sessionId, body) => {
    gateway.sent = { sessionId, ...body };
    return { start_event_id: 1, status: 'running' };
  };
  gateway.events = async function* () {
    yield { event_id: 1, event: 'turn.delta', data: { request_id: gateway.sent.request_id, delta: 'Jaeger ' } };
    yield { event_id: 2, event: 'turn.finish', data: { request_id: gateway.sent.request_id } };
  };
  gateway.receipt = async () => ({ status: 'completed', result: { output: 'Jaeger answer' } });
  gateway.session = async sessionId => ({ session_id: sessionId, messages: [] });

  const responses = [];
  const stream = { markdown: text => responses.push(text), progress: () => {} };
  const token = { isCancellationRequested: false, onCancellationRequested: () => ({ dispose() {} }) };
  const first = await handler({ prompt: 'First question' }, { history: [] }, stream, token);
  assert.ok(first, responses.join('\n'));
  const sessionId = first.metadata.jaegerSessionId;
  const second = await handler({ prompt: 'Follow-up' }, { history: [{ result: first }] }, stream, token);

  assert.equal(createdSessions.length, 1);
  assert.equal(gateway.sent.sessionId, sessionId);
  assert.equal(gateway.sent.text, 'Follow-up');
  assert.equal(second.metadata.jaegerSessionId, sessionId);
  assert.deepEqual(responses, ['Jaeger ', 'answer', 'Jaeger ', 'answer']);
});

test('native chat answers editor requests once through the shared panel bridge', async () => {
  const wired = wireExtension();
  wired.send({ type: 'ready' });
  await waitFor(() => wired.gateway.instance !== undefined);
  const handler = chatParticipants.get('jaeger.chatParticipant');
  const gateway = wired.gateway.instance;
  gateway.create = async body => ({ session_id: body.session_id });
  gateway.send = async (sessionId, body) => {
    gateway.sent = { sessionId, ...body };
    return { start_event_id: 1, status: 'running' };
  };
  const answers = [];
  gateway.ideResult = async (sid, id, body) => {
    answers.push({ sid, id, body });
    if (id === 'expired') throw new Error('Another client already answered');
  };
  gateway.events = async function* () {
    const sid = gateway.sent.sessionId, rid = gateway.sent.request_id;
    const request = (event_id, id, kind, extra = {}) => ({
      event_id, event: 'ide.request', session_id: sid,
      data: { request_id: rid, ide_request_id: id, kind, args: {} }, ...extra,
    });
    yield request(1, 'foreign-session', 'context', { session_id: 'other-session' });
    yield request(2, 'foreign-turn', 'context', { data: { request_id: 'other-turn', ide_request_id: 'foreign-turn', kind: 'context' } });
    yield request(3, 'context', 'context');
    yield request(3, 'context', 'context'); // replay must not reopen an editor
    yield request(4, 'unsupported', 'unsupported');
    yield request(5, 'expired', 'diagnostics');
    yield request(6, undefined, 'context');
    yield { event_id: 7, event: 'turn.finish', data: { request_id: rid } };
  };
  gateway.receipt = async () => ({ status: 'completed', result: { output: 'Done' } });
  gateway.session = async sessionId => ({ session_id: sessionId, messages: [] });
  const responses = [];
  const result = await handler({ prompt: 'Inspect the editor' }, { history: [] },
    { markdown: text => responses.push(text), progress() {} },
    { isCancellationRequested: false, onCancellationRequested: () => ({ dispose() {} }) });
  assert.deepEqual(answers.map(a => a.id), ['context', 'unsupported', 'expired']);
  assert.ok(answers.every(a => a.sid === result.metadata.jaegerSessionId));
  assert.deepEqual(answers[0].body, { ok: true, result: { workspace_folders: ['/workspace/one'] } });
  assert.deepEqual(answers[1].body, { ok: false, error: 'Unsupported IDE request: unsupported' });
  assert.deepEqual(answers[2].body, { ok: true, result: { count: 0, diagnostics: [], truncated: false } });
  assert.deepEqual(responses, ['Done'], 'an expired editor request must not fail the turn');
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

test('@ mention stages the picked workspace file through the Gateway attachment contract', async () => {
  const { send, gateway, posted } = wireExtension();
  send({ type: 'ready' });
  await waitFor(() => gateway.instance !== undefined);
  gateway.instance.sessions = async () => ({ sessions: [{ session_id: 'mention', title: 'T', status: 'idle', messages: [] }] });
  gateway.instance.session = async id => ({ session_id: id, title: 'T', status: 'idle', messages: [] });
  const attachments = [];
  gateway.instance.addAttachment = async (_sid, body) => {
    attachments.push(body);
    return { attachment_id: 'mention-attachment', original_filename: body.filename };
  };
  send({ type: 'select', id: 'mention' });
  await new Promise(r => setTimeout(r, 50));

  send({ type: 'mentionFile' });
  await waitFor(() => posted.some(message => message.mention === '@src/main.py'));
  assert.deepEqual(attachments, [{
    path: '/workspace/one/src/main.py',
    filename: 'main.py',
    mime: 'text/x-python',
    size: 0,
  }]);
});

test('pasteAttachment writes data to attachment scratch and stages it through Gateway', async () => {
  const { send, gateway, posted } = wireExtension();
  send({ type: 'ready' });
  await waitFor(() => gateway.instance !== undefined);
  gateway.instance.sessions = async () => ({ sessions: [{ session_id: 'paste-session', title: 'T', status: 'idle', messages: [] }] });
  gateway.instance.session = async id => ({ session_id: id, title: 'T', status: 'idle', messages: [] });
  const attachments = [];
  gateway.instance.addAttachment = async (_sid, body) => {
    attachments.push(body);
    return { attachment_id: 'pasted-attachment', original_filename: body.filename };
  };
  send({ type: 'select', id: 'paste-session' });
  await new Promise(r => setTimeout(r, 50));

  send({
    type: 'pasteAttachment',
    name: 'clipboard.png',
    mime: 'image/png',
    data: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  });
  await waitFor(() => attachments.length > 0);
  assert.equal(attachments[0].filename, 'clipboard.png');
  assert.equal(attachments[0].mime, 'image/png');
  assert.match(attachments[0].path, /clipboard\.png$/);
  assert.match(attachments[0].path, /^\/tmp\/jaeger-extension-global-storage-test\/attachments\//);
  assert.doesNotMatch(attachments[0].path, /\/workspace\/one\/\.jaeger\//);
});

test('copy message action reaches the native IDE clipboard', async () => {
  copiedText = null;
  const { send, gateway, posted } = wireExtension();
  send({ type: 'ready' });
  await waitFor(() => gateway.instance !== undefined);
  send({ type: 'copy', text: 'copied from Jaeger' });
  await waitFor(() => copiedText === 'copied from Jaeger');
  assert.equal(copiedText, 'copied from Jaeger');
});

test('model "config" → jaeger.model setting reaches admission body', async () => {
  jaegerModelSetting = 'my-static-model';
  const { send, gateway, posted } = wireExtension();
  send({ type: 'ready' });
  await waitFor(() => gateway.instance !== undefined);
  // Simulate a connected session so send() goes through.
  gateway.instance.sessions = async () => ({ sessions: [{ session_id: 'sid', title: 'T', status: 'idle', messages: [] }] });
  gateway.instance.session = async id => ({ session_id: id, title: 'T', status: 'idle', messages: [] });
  send({ type: 'select', id: 'sid' });
  await new Promise(r => setTimeout(r, 50));
  await send({ type: 'send', text: 'hello', model: 'config' });
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
  await send({ type: 'send', text: 'hello', model: 'openai::gpt-4' });
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

  await send1({ type: 'send', text: 'q', model: 'anthropic::gpt-4' });
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

test('ready handshake replays the latest connection state after controller startup', async () => {
  const { send, posted } = wireExtension();
  await send({ type: 'ready' });
  await waitFor(() => posted.some(message => message.connected === true));
  const connectedStates = posted.filter(message => message.connected === true);
  assert.ok(connectedStates.length >= 1, 'extension must deliver a connected state after ready');
  assert.equal(connectedStates.at(-1).status, 'Connected');
});

const cloudCatalog = model => ({ providers: [
  { id: 'ollama-cloud', reachable: true, models: [{ id: model, available: true }] },
] });

async function connectedWire(modelCatalog) {
  const wired = wireExtension({ catalog: modelCatalog });
  await wired.send({ type: 'ready' });
  await wired.send({ type: 'select', id: 'cloud-session' });
  await waitFor(() => wired.posted.some(state => state.connected && state.models));
  return wired;
}

test('discovered Ollama Cloud default persists and reaches immediate and queued admissions unchanged', async () => {
  const model = 'fixture-cloud-cognition:cloud';
  const wired = await connectedWire(cloudCatalog(model));
  chooseItem = items => items.find(item => item.modelValue === `ollama-cloud::${model}`);
  await registeredCommands.get('jaeger.selectModel')();
  assert.equal(jaegerModelSetting, `ollama-cloud::${model}`);
  await wired.send({ type: 'send', text: 'synthetic turn', model: 'config', ideContext: false });
  assert.deepEqual({ provider: wired.gateway.sent.provider, model: wired.gateway.sent.model },
    { provider: 'ollama-cloud', model });
  await wired.send({ type: 'queue', text: 'synthetic follow-up', model: 'config', ideContext: false });
  assert.equal(wired.gateway.queued.sid, 'cloud-session');
  assert.deepEqual({ provider: wired.gateway.queued.body.provider, model: wired.gateway.queued.body.model },
    { provider: 'ollama-cloud', model });
  wired.dispose();
});

test('routed catalog ID is decoded once before default admission', async () => {
  const model = 'fixture-routed:cloud';
  const wired = await connectedWire(cloudCatalog(`@ollama-cloud:${model}`));
  chooseItem = items => items.find(item => item.label === model);
  await registeredCommands.get('jaeger.selectModel')();
  await wired.send({ type: 'send', text: 'synthetic turn', model: 'config', ideContext: false });
  assert.deepEqual({ provider: wired.gateway.sent.provider, model: wired.gateway.sent.model },
    { provider: 'ollama-cloud', model });
  wired.dispose();
});

for (const [name, modelCatalog, selection] of [
  ['unavailable provider', { providers: [{ id: 'ollama-cloud', reachable: false, models: [{ id: 'fixture-model', available: true }] }] }, 'ollama-cloud::fixture-model'],
  ['suffix collision', cloudCatalog('other:fixture-model'), 'ollama-cloud::fixture-model'],
  ['empty catalog', { providers: [] }, 'ollama-cloud::fixture-model'],
]) {
  test(`${name} rejects send and queue without replacing the selected model`, async () => {
    jaegerModelSetting = selection;
    const wired = await connectedWire(modelCatalog);
    await wired.send({ type: 'send', text: 'must not be admitted', model: 'config' });
    await wired.send({ type: 'queue', text: 'must not be queued', model: 'config' });
    assert.equal(wired.gateway.sent, null);
    assert.equal(wired.gateway.queued, null);
    assert.equal(jaegerModelSetting, selection);
    assert.ok(wired.posted.some(state => /unavailable|catalog/i.test(state.error || '')));
    wired.dispose();
  });
}

test('native chat approval action opens the owning existing conversation', async () => {
  const wired = wireExtension(); await wired.send({ type: 'ready' });
  const gateway = wired.gateway.instance;
  gateway.create = async body => ({ session_id: body.session_id });
  gateway.send = async (sid, body) => { gateway.sent = { sid, ...body }; return { status: 'running', start_event_id: 1 }; };
  gateway.events = async function* () {
    yield { event_id: 1, event: 'approval.request', data: { request_id: gateway.sent.request_id, approval_id: 'a' } };
    yield { event_id: 2, event: 'turn.finish', data: { request_id: gateway.sent.request_id } };
  };
  gateway.receipt = async () => ({ status: 'completed', result: { output: 'Done' } });
  const buttons = [], progress = [], opened = [];
  const result = await chatParticipants.get('jaeger.chatParticipant')({ prompt: 'Inspect' }, { history: [] },
    { markdown() {}, progress: text => progress.push(text), button: button => buttons.push(button) },
    { isCancellationRequested: false, onCancellationRequested: () => ({ dispose() {} }) });
  assert.match(progress.join('\n'), /Waiting for your approval/);
  assert.equal(buttons[0].command, 'jaeger.openSession');
  assert.deepEqual(buttons[0].arguments, [result.metadata.jaegerSessionId]);
  gateway.session = async id => { opened.push(id); return { session_id: id, status: 'idle', messages: [] }; };
  await registeredCommands.get(buttons[0].command)(...buttons[0].arguments);
  assert.ok(opened.includes(result.metadata.jaegerSessionId), JSON.stringify(wired.posted.filter(x => x.error)));
});

test('native chat cancellation during admission is sent once after acceptance and remains unconfirmed', async () => {
  const wired = wireExtension(); await wired.send({ type: 'ready' });
  const gateway = wired.gateway.instance;
  let cancelCallback, accepted = false; const cancellations = [], text = [];
  gateway.create = async body => ({ session_id: body.session_id });
  gateway.send = async (sid, body) => { cancelCallback(); accepted = true; return { status: 'running', start_event_id: 1 }; };
  gateway.cancel = async (...args) => { assert.equal(accepted, true); cancellations.push(args); };
  gateway.receipt = async () => ({ status: 'running' });
  gateway.events = async function* () { assert.fail('an aborted observer should not open a stream'); };
  const result = await chatParticipants.get('jaeger.chatParticipant')({ prompt: 'Inspect' }, { history: [] },
    { markdown: value => text.push(value), progress() {}, button() {} },
    { isCancellationRequested: false, onCancellationRequested: cb => { cancelCallback = cb; return { dispose() {} }; } });
  assert.equal(cancellations.length, 1);
  assert.deepEqual(cancellations[0], [result.metadata.jaegerSessionId, result.metadata.jaegerRequestId]);
  assert.match(text.join(''), /Cancellation requested.*not confirmed/s);
});

test('selected workspace controls automatic admission context and mention search root', async () => {
  jaegerModelSetting = '';
  const wired = wireExtension(); await wired.send({ type: 'ready' });
  await wired.send({ type: 'selectWorkspace' });
  await wired.send({ type: 'select', id: 'context-session' });
  mockVscode.window.activeTextEditor = { document: { uri: { scheme: 'file', fsPath: '/workspace/one/private.py' }, getText() { assert.fail('outside selection must not be read'); } },
    selection: { isEmpty: false, start: { line: 0 }, end: { line: 1 }, active: { line: 1 } } };
  const oldFind = mockVscode.workspace.findFiles;
  let searched;
  mockVscode.workspace.findFiles = async pattern => { searched = pattern; return [{ fsPath: '/workspace/two/main.py' }]; };
  try {
    await wired.send({ type: 'send', text: 'Inspect', model: '' });
    assert.deepEqual(wired.gateway.sent.options.ide, { workspace_folders: ['/workspace/two'] });
    await wired.send({ type: 'mentionFile' });
    assert.equal(searched.base, '/workspace/two');
  } finally { mockVscode.window.activeTextEditor = undefined; mockVscode.workspace.findFiles = oldFind; }
});

test('native chat preserves request identity after an uncertain admission instead of inviting a resend', async () => {
  const wired = wireExtension(); await wired.send({ type: 'ready' });
  const gateway = wired.gateway.instance; let sends = 0; const text = [], buttons = [];
  gateway.create = async body => ({ session_id: body.session_id });
  gateway.send = async () => { sends++; throw new Error('connection reset after POST'); };
  const result = await chatParticipants.get('jaeger.chatParticipant')({ prompt: 'Inspect' }, { history: [] },
    { markdown: value => text.push(value), progress() {}, button: value => buttons.push(value) },
    { isCancellationRequested: false, onCancellationRequested: () => ({ dispose() {} }) });
  assert.equal(sends, 1);
  assert.ok(result.metadata.jaegerRequestId);
  assert.match(text.join(''), /outcome is not confirmed/);
  assert.deepEqual(buttons[0].arguments, [result.metadata.jaegerSessionId]);
});

function workspaceFixture() {
  const fs = require('node:fs'), os = require('node:os');
  const scratch = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'jaeger-context-regression-')));
  const a = path.join(scratch, 'a'), b = path.join(scratch, 'b');
  fs.mkdirSync(a); fs.mkdirSync(b);
  const fileA = path.join(a, 'a.py'), fileB = path.join(b, 'b.py');
  fs.writeFileSync(fileA, 'A selection'); fs.writeFileSync(fileB, 'B private selection');
  const oldFolders = mockVscode.workspace.workspaceFolders, oldPick = mockVscode.window.showWorkspaceFolderPick;
  const oldEditor = mockVscode.window.activeTextEditor, oldDiagnostics = mockVscode.languages.getDiagnostics;
  mockVscode.workspace.workspaceFolders = [a, b].map(fsPath => ({ uri: { fsPath } }));
  mockVscode.window.showWorkspaceFolderPick = async () => ({ uri: { fsPath: b } });
  const editor = (file, text, scheme = 'file') => ({
    document: { uri: { scheme, fsPath: file }, languageId: 'python', getText: typeof text === 'function' ? text : () => text },
    selection: { isEmpty: false, start: { line: 0 }, end: { line: 1 }, active: { line: 1 } },
  });
  return { fs, a, b, fileA, fileB, editor, close() {
    mockVscode.workspace.workspaceFolders = oldFolders; mockVscode.window.showWorkspaceFolderPick = oldPick;
    mockVscode.window.activeTextEditor = oldEditor; mockVscode.languages.getDiagnostics = oldDiagnostics;
    fs.rmSync(scratch, { recursive: true, force: true });
  } };
}

const nativeTestStream = () => ({ markdown() {}, progress() {}, button() {} });
const nativeTestToken = { isCancellationRequested: false, onCancellationRequested: () => ({ dispose() {} }) };

test('native workspace snapshot stays in A when session creation awaits and the editor switches to B', async () => {
  const f = workspaceFixture(); let wired;
  try {
    jaegerModelSetting = '';
    mockVscode.window.activeTextEditor = f.editor(f.fileA, 'A selection');
    wired = wireExtension(); await wired.send({ type: 'ready' });
    const gateway = wired.gateway.instance;
    let releaseCreate, notifyCreate;
    const started = new Promise(resolve => { notifyCreate = resolve; });
    gateway.create = async body => {
      assert.equal(body.workspace, f.a); notifyCreate();
      await new Promise(resolve => { releaseCreate = resolve; });
      return { session_id: body.session_id };
    };
    gateway.send = async (sid, body) => { gateway.sent = body; return { status: 'completed' }; };
    gateway.receipt = async () => ({ status: 'completed', result: { output: 'Done' } });
    const turn = chatParticipants.get('jaeger.chatParticipant')({ prompt: 'Inspect A' }, { history: [] }, nativeTestStream(), nativeTestToken);
    await started;
    await wired.send({ type: 'selectWorkspace' });
    mockVscode.window.activeTextEditor = f.editor(f.fileB, 'B private selection');
    releaseCreate(); await turn;
    assert.equal(gateway.sent.workspace, f.a);
    assert.deepEqual(gateway.sent.options.ide.workspace_folders, [f.a]);
    assert.equal(gateway.sent.options.ide.active_file, 'a.py');
    assert.equal(gateway.sent.options.ide.selection.text, 'A selection');
    assert.doesNotMatch(JSON.stringify(gateway.sent), /B private selection|b\.py/);
  } finally { wired?.dispose(); f.close(); }
});

test('queued workspace snapshot stays in A while queue admission awaits a switch to B', async () => {
  const f = workspaceFixture(); let wired;
  try {
    jaegerModelSetting = '';
    mockVscode.window.activeTextEditor = f.editor(f.fileA, 'A selection');
    wired = wireExtension(); await wired.send({ type: 'ready' }); await wired.send({ type: 'select', id: 'queue-context' });
    const gateway = wired.gateway.instance;
    let releaseQueue, notifyQueue, queuedBody;
    const started = new Promise(resolve => { notifyQueue = resolve; });
    gateway.queueAdd = async (sid, body) => {
      queuedBody = body; notifyQueue();
      await new Promise(resolve => { releaseQueue = resolve; });
      return { status: 'queued' };
    };
    const queued = wired.send({ type: 'queue', text: 'Inspect A later', model: '' });
    await started;
    await wired.send({ type: 'selectWorkspace' });
    mockVscode.window.activeTextEditor = f.editor(f.fileB, 'B private selection');
    releaseQueue(); await queued;
    assert.equal(queuedBody.workspace, f.a);
    assert.equal(queuedBody.options.ide.selection.text, 'A selection');
    assert.deepEqual(queuedBody.options.ide.workspace_folders, [f.a]);
    assert.doesNotMatch(JSON.stringify(queuedBody), /B private selection|b\.py/);
  } finally { wired?.dispose(); f.close(); }
});

test('deleted symlink backing files fail closed for selection diagnostics and opens; untitled text is omitted', async () => {
  const f = workspaceFixture(); let wired;
  try {
    const link = path.join(f.a, 'outside'); f.fs.symlinkSync(f.b, link, 'dir');
    const vanished = path.join(f.b, 'vanished.py'); f.fs.writeFileSync(vanished, 'private');
    const bufferPath = path.join(link, 'vanished.py'); f.fs.unlinkSync(vanished);
    let selectionReads = 0;
    mockVscode.window.activeTextEditor = f.editor(bufferPath, () => { selectionReads++; return 'private removed-file buffer'; });
    mockVscode.languages.getDiagnostics = () => [[{ scheme: 'file', fsPath: bufferPath }, [
      { severity: 0, range: { start: { line: 0 } }, message: 'private diagnostic text' },
    ]]];
    jaegerModelSetting = '';
    wired = wireExtension(); await wired.send({ type: 'ready' });
    const gateway = wired.gateway.instance, answers = [];
    gateway.create = async body => ({ session_id: body.session_id });
    gateway.send = async (sid, body) => { gateway.sent = body; return { status: 'running', start_event_id: 1 }; };
    gateway.ideResult = async (sid, id, body) => { answers.push({ id, body }); };
    gateway.events = async function* () {
      for (const [i, kind] of ['context', 'diagnostics', 'open_file'].entries()) {
        yield { event_id: i + 1, event: 'ide.request', data: { request_id: gateway.sent.request_id,
          ide_request_id: kind, kind, args: { path: bufferPath } } };
      }
      yield { event_id: 4, event: 'turn.finish', data: { request_id: gateway.sent.request_id } };
    };
    gateway.receipt = async () => ({ status: 'completed', result: { output: 'Done' } });
    const handler = chatParticipants.get('jaeger.chatParticipant');
    await handler({ prompt: 'Inspect editor' }, { history: [] }, nativeTestStream(), nativeTestToken);
    assert.equal(selectionReads, 0, 'unresolved symlink-backed buffer must never be read');
    assert.equal(gateway.sent.options.ide.selection, undefined);
    assert.equal(answers.find(a => a.id === 'context').body.result.active_file, undefined);
    assert.deepEqual(answers.find(a => a.id === 'diagnostics').body.result, { count: 0, diagnostics: [], truncated: false });
    assert.deepEqual(answers.find(a => a.id === 'open_file').body, { ok: false, error: 'Editor request is outside the selected workspace.' });
    assert.doesNotMatch(JSON.stringify([gateway.sent, answers]), /private removed-file buffer|private diagnostic text/);
    mockVscode.window.activeTextEditor = f.editor('Untitled-1', () => { assert.fail('untitled text must not be read automatically'); }, 'untitled');
    await handler({ prompt: 'Inspect again' }, { history: [] }, nativeTestStream(), nativeTestToken);
    assert.equal(gateway.sent.options.ide.active_file, undefined);
    assert.equal(gateway.sent.options.ide.selection, undefined);
  } finally { wired?.dispose(); f.close(); }
});

test('permission picker reads Gateway state and applies only the chosen supported mode', async () => {
  const wired = wireExtension();
  try {
    await wired.send({ type: 'ready' });
    const gw = wired.gateway.instance; let saved;
    gw.autonomy = async () => ({ autonomy: 'scoped', options: ['ask', 'scoped', 'auto'] });
    gw.setAutonomy = async mode => { saved = mode; return { autonomy: mode, options: ['ask', 'scoped', 'auto'] }; };
    chooseItem = items => items.find(item => item.mode === 'ask');
    await wired.send({ type: 'gatewayPermissions' });
    assert.equal(saved, 'ask');
    assert.ok(wired.posted.some(item => item.autonomy?.mode === 'ask'));
    chooseItem = () => undefined;
    saved = undefined;
    await wired.send({ type: 'gatewayPermissions' });
    assert.equal(saved, undefined);
  } finally { wired.dispose(); }
});

test('Local execution menu chooses a workspace without changing Gateway permissions', async () => {
  const wired = wireExtension();
  try {
    await wired.send({ type: 'ready' });
    chooseItem = items => items.find(item => item.action === 'workspace');
    await wired.send({ type: 'executionLocation' });
    assert.ok(wired.posted.some(item => item.selectedWorkspace === '/workspace/two'));
  } finally { wired.dispose(); }
});

test('Gateway model refresh reloads the catalog instead of keeping the first snapshot forever', async () => {
  const wired = wireExtension();
  try {
    await wired.send({ type: 'ready' });
    const gw = wired.gateway.instance; let reads = 0;
    gw.models = async () => { reads++; return { providers: [{ id: 'changed', reachable: true, models: [{ id: 'new-model' }] }] }; };
    await wired.send({ type: 'refreshModels' });
    assert.equal(reads, 1);
    assert.ok(wired.posted.some(item => item.models?.providers?.[0]?.id === 'changed'));
  } finally { wired.dispose(); }
});
